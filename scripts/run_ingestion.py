"""Initial-backfill runner: processes locally downloaded openFDA/DailyMed bulk
files (fetched by scripts/download_bulk_data.py) through the existing,
already-tested ingestion pipeline (ingestion/openfda/run.py,
ingestion/dailymed/run.py). No network access for the data itself -- only a
DB connection.

Order: openFDA first, then DailyMed. openFDA's flat per-record JSON shape is
simpler than DailyMed's nested-zip-of-zips-of-XML structure
(DAILYMED_INGESTION.md calls DailyMed "architecturally the harder of the two
phase-1 sources"), and openFDA is the most real-data-tested adapter in this
project. Getting the simpler source's real-scale behavior (dedup, DLQ,
entity resolution) confirmed correct first, before the harder source, before
cross-source entity resolution (ENTITY_RESOLUTION.md) has two sources'
canonical records to actually reconcile against each other.

Commit granularity: one commit per *file* (one openFDA partition, one
DailyMed outer release zip) -- not one commit for the whole multi-file
backfill, and not one per record.

ingest_drug_label_records()/ingest_spl_documents() checkpoint via
session.flush(), not session.commit() -- flush pushes SQL into the open
transaction but isn't durable until commit. Chaining every partition/zip into
one call with a single commit at the very end would mean a crash 90% through
a multi-hour run loses everything ingested so far, since nothing was ever
committed -- the checkpoint/resume machinery those functions already have
would never get a chance to matter. Committing after each file bounds the
worst-case redo on a crash to "one partition" (~20k records, minutes) or "one
release zip" (~3GB / 10k-15k packages, could still be a real chunk of an
hour) instead of the entire backfill. Still not as tight as committing at
every internal checkpoint batch -- that would require changing
ingest_drug_label_records/ingest_spl_documents themselves to commit instead
of flush, which is a real, separate improvement to the tested ingestion
modules, not something bolted on from a caller. Noted, not silently glossed
over.

Usage:
    uv run python scripts/run_ingestion.py --dry-run          # list files, no DB writes
    uv run python scripts/run_ingestion.py --source openfda
    uv run python scripts/run_ingestion.py --source dailymed
    uv run python scripts/run_ingestion.py --source all       # default

--bulk-dir defaults to <repo root>/data/bulk. If your files were downloaded
before download_bulk_data.py's own default was fixed to be repo-root-anchored,
they may actually be sitting under scripts/data/bulk instead -- pass
`--bulk-dir scripts/data/bulk` explicitly in that case (--dry-run first to
confirm which path finds your files).
"""

import argparse
import os
import sys
import time
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TypeVar

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    # Running this file directly (`python scripts/run_ingestion.py`) puts
    # scripts/ on sys.path, not the repo root -- `import ingestion...` would
    # otherwise fail unless the caller already set PYTHONPATH themselves.
    sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from ingestion.dailymed.discovery import discover_packages  # noqa: E402
from ingestion.dailymed.extraction import iter_spl_packages  # noqa: E402
from ingestion.dailymed.run import ingest_spl_documents  # noqa: E402
from ingestion.openfda.bulk import iter_records_from_bulk_zip  # noqa: E402
from ingestion.openfda.bulk_manifest import fetch_download_manifest, list_partitions  # noqa: E402
from ingestion.openfda.parser import parse_drug_label_record  # noqa: E402
from ingestion.openfda.run import ingest_drug_label_records  # noqa: E402

DEFAULT_BULK_DIR = REPO_ROOT / "data" / "bulk"

DAILYMED_CATEGORIES = ("human_rx", "human_otc")

T = TypeVar("T")


# --- progress reporting -----------------------------------------------------
# Prints to a single, in-place-overwritten line (\r, no trailing newline until
# the file finishes) -- console output stays a constant size regardless of
# whether a file has 1,000 or 20,000 records. Nothing here holds accumulated
# log text in memory either; each print discards the previous line.


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def with_progress(
    items: Iterable[T], *, label: str, total: int | None, interval: float = 1.0
) -> Iterator[T]:
    """Pass items through unchanged, printing a throttled progress line.

    `total=None` (unknown item count) still shows count/rate/elapsed, just no
    percent or ETA -- graceful degradation rather than a hard requirement.
    """
    start = time.monotonic()
    count = 0
    last_print = 0.0
    for item in items:
        count += 1
        now = time.monotonic()
        if now - last_print >= interval:
            _print_progress(label, count, total, start)
            last_print = now
        yield item
    _print_progress(label, count, total, start)
    sys.stdout.write("\n")


def _print_progress(label: str, count: int, total: int | None, start: float) -> None:
    elapsed = time.monotonic() - start
    rate = count / elapsed if elapsed > 0 else 0.0
    if total:
        pct = min(count / total * 100, 100.0)
        bar_width = 24
        filled = min(int(bar_width * count / total), bar_width)
        bar = "#" * filled + "-" * (bar_width - filled)
        eta = (total - count) / rate if rate > 0 and count < total else 0.0
        msg = (
            f"\r  [{bar}] {label} {count}/{total} ({pct:.1f}%) "
            f"{rate:.0f}/s elapsed={_format_duration(elapsed)} eta={_format_duration(eta)}"
        )
    else:
        msg = f"\r  {label}: {count} processed, {rate:.0f}/s, elapsed={_format_duration(elapsed)}"
    sys.stdout.write(msg.ljust(100))
    sys.stdout.flush()


def _openfda_record_counts() -> dict[str, int]:
    """Exact per-partition record counts from openFDA's own manifest --
    matched by filename, so the progress bar's denominator is real, not
    guessed. Falls back to an empty dict (indeterminate progress for every
    file) if the manifest can't be reached -- offline runs still work, just
    without percent/ETA.
    """
    try:
        with httpx.Client(timeout=15.0) as client:
            manifest = fetch_download_manifest(client)
        bulk_partitions = list_partitions(manifest, category="drug", endpoint="label")
        return {Path(p.file_url).name: p.records for p in bulk_partitions}
    except (httpx.HTTPError, KeyError):
        print("  (couldn't reach openFDA's manifest -- progress will be indeterminate)")
        return {}


def _dailymed_package_count(zip_path: Path) -> int:
    """Number of nested package ZIPs in this release file -- read from the
    outer ZIP's central directory only (fast: no decompression), same call
    the real ingestion path uses to discover packages in the first place.
    """
    with zipfile.ZipFile(zip_path) as outer:
        return len(discover_packages(outer))


def _openfda_partitions(bulk_dir: Path) -> list[Path]:
    return sorted((bulk_dir / "openfda" / "drug" / "label").glob("*.json.zip"))


def _dailymed_zips(bulk_dir: Path) -> list[Path]:
    full_release = bulk_dir / "dailymed" / "full_release"
    return [
        zip_path
        for category in DAILYMED_CATEGORIES
        for zip_path in sorted((full_release / category).glob("*.zip"))
    ]


def list_files(bulk_dir: Path, source: str) -> None:
    if source in ("openfda", "all"):
        partitions = _openfda_partitions(bulk_dir)
        print(f"openFDA: {len(partitions)} partition file(s) under {bulk_dir / 'openfda'}")
        for path in partitions:
            print(f"  {path.relative_to(bulk_dir)}")
    if source in ("dailymed", "all"):
        zips = _dailymed_zips(bulk_dir)
        print(f"DailyMed: {len(zips)} release file(s) under {bulk_dir / 'dailymed/full_release'}")
        for path in zips:
            print(f"  {path.relative_to(bulk_dir)}")


def run_openfda(session: Session, bulk_dir: Path) -> None:
    partitions = _openfda_partitions(bulk_dir)
    if not partitions:
        print(f"no openFDA partition files found under {bulk_dir / 'openfda/drug/label'}")
        return

    record_counts = _openfda_record_counts()
    run_start = time.monotonic()

    for i, partition_path in enumerate(partitions, start=1):
        print(f"[openfda {i}/{len(partitions)}] {partition_path.name}")
        file_start = time.monotonic()
        raw_records = with_progress(
            iter_records_from_bulk_zip(partition_path),
            label=partition_path.name,
            total=record_counts.get(partition_path.name),
        )
        records = (parse_drug_label_record(raw) for raw in raw_records)
        log = ingest_drug_label_records(
            session, records, endpoint=f"drug/label:bulk:{partition_path.stem}"
        )
        session.commit()
        print(
            f"  status={log.status.value} fetched={log.records_fetched} "
            f"created={log.records_created} updated={log.records_updated} "
            f"unchanged={log.records_unchanged} rejected={log.records_rejected} "
            f"took={_format_duration(time.monotonic() - file_start)}"
        )

    print(f"openFDA done in {_format_duration(time.monotonic() - run_start)}")


def run_dailymed(session: Session, bulk_dir: Path) -> None:
    zip_paths = _dailymed_zips(bulk_dir)
    if not zip_paths:
        print(f"no DailyMed release files found under {bulk_dir / 'dailymed/full_release'}")
        return

    run_start = time.monotonic()

    for i, zip_path in enumerate(zip_paths, start=1):
        print(f"[dailymed {i}/{len(zip_paths)}] {zip_path.relative_to(bulk_dir)}")
        file_start = time.monotonic()
        total_packages = _dailymed_package_count(zip_path)
        packages = with_progress(
            iter_spl_packages(str(zip_path)), label=zip_path.name, total=total_packages
        )
        log = ingest_spl_documents(session, packages, endpoint=f"spl:bulk:{zip_path.stem}")
        session.commit()
        print(
            f"  status={log.status.value} fetched={log.records_fetched} "
            f"created={log.records_created} updated={log.records_updated} "
            f"unchanged={log.records_unchanged} rejected={log.records_rejected} "
            f"took={_format_duration(time.monotonic() - file_start)}"
        )

    print(f"DailyMed done in {_format_duration(time.monotonic() - run_start)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["openfda", "dailymed", "all"], default="all")
    parser.add_argument("--bulk-dir", type=Path, default=DEFAULT_BULK_DIR)
    parser.add_argument(
        "--dry-run", action="store_true", help="List files that would be processed; no DB writes"
    )
    args = parser.parse_args()

    if args.dry_run:
        list_files(args.bulk_dir, args.source)
        return

    load_dotenv(REPO_ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL not set (check .env)")

    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    run_start = time.monotonic()
    print(f"started {started_at}\n")

    engine = create_engine(database_url)
    with Session(engine) as session:
        if args.source in ("openfda", "all"):
            run_openfda(session, args.bulk_dir)
        if args.source in ("dailymed", "all"):
            run_dailymed(session, args.bulk_dir)

    print(f"\ntotal run time: {_format_duration(time.monotonic() - run_start)}")


if __name__ == "__main__":
    main()
