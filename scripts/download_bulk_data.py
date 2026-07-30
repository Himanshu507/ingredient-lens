"""Resumable downloader for the openFDA/DailyMed bulk files listed in
docs/openfda_downloads.md and docs/dailymed_download.md.

Reads the URL list straight out of those two docs (single source of truth --
editing the docs changes what this script downloads, nothing hardcoded here
needs updating in step), and lays files out under --dest in a structure that
mirrors how the docs group them:

    data/bulk/
      openfda/
        label/drug-label-0001-of-0014.json.zip ...
        enforcement/drug-enforcement-0001-of-0001.json.zip
      dailymed/
        full_release/human_rx/dm_spl_release_human_rx_part1.zip ...
        full_release/human_otc/...
        full_release/homeopathic|animal|remainder/...
        incremental/daily|weekly|monthly/...

Resume: each file downloads to a `<name>.part` sibling. A dropped connection
leaves the `.part` on disk; re-running the script sends `Range:
bytes=<existing size>-` and appends, rather than restarting from zero. Only
renamed to its final name once the stream completes without error. If the
server doesn't honor the Range request (some do not), the partial content is
discarded and that one file restarts from zero -- everything else already
completed is untouched.

Usage:
    uv run python scripts/download_bulk_data.py
    uv run python scripts/download_bulk_data.py --source openfda --dest /Volumes/big-disk/rie-data
"""

import argparse
import re
import sys
import time
from pathlib import Path

import httpx

URL_PATTERN = re.compile(r"https://\S+?\.zip")
REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_DEST = REPO_ROOT / "data" / "bulk"

MAX_RETRIES = 8
INITIAL_RETRY_DELAY_SECONDS = 2.0
MAX_RETRY_DELAY_SECONDS = 60.0
CHUNK_SIZE = 1 << 20  # 1 MiB
PROGRESS_INTERVAL_SECONDS = 1.0


def extract_urls(md_path: Path) -> list[str]:
    text = md_path.read_text()
    return list(dict.fromkeys(URL_PATTERN.findall(text)))  # de-dup, preserve order


def bucket_for(url: str) -> Path:
    if "download.open.fda.gov" in url:
        # https://download.open.fda.gov/drug/label/drug-label-0001-of-0014.json.zip
        path_parts = url.split("download.open.fda.gov/", 1)[1].split("/")
        return Path("openfda", *path_parts[:-1])

    if "dailymed-data.nlm.nih.gov" in url:
        filename = url.rsplit("/", 1)[-1]
        prefixes = {
            "dm_spl_release_human_rx": ("full_release", "human_rx"),
            "dm_spl_release_human_otc": ("full_release", "human_otc"),
            "dm_spl_release_homeopathic": ("full_release", "homeopathic"),
            "dm_spl_release_animal": ("full_release", "animal"),
            "dm_spl_release_remainder": ("full_release", "remainder"),
            "dm_spl_daily_update": ("incremental", "daily"),
            "dm_spl_weekly_update": ("incremental", "weekly"),
            "dm_spl_monthly_update": ("incremental", "monthly"),
        }
        for prefix, subpath in prefixes.items():
            if filename.startswith(prefix):
                return Path("dailymed", *subpath)
        return Path("dailymed", "other")

    return Path("other")


def _format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _print_progress(name: str, downloaded: int, total: int | None) -> None:
    if total:
        pct = downloaded / total * 100
        msg = f"\r  {name}: {_format_bytes(downloaded)} / {_format_bytes(total)} ({pct:.1f}%)"
    else:
        msg = f"\r  {name}: {_format_bytes(downloaded)}"
    sys.stdout.write(msg.ljust(80))
    sys.stdout.flush()


def _download_once(client: httpx.Client, url: str, dest_path: Path) -> str:
    if dest_path.exists():
        return "already downloaded"

    part_path = dest_path.with_name(dest_path.name + ".part")
    resume_from = part_path.stat().st_size if part_path.exists() else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}

    with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
        if response.status_code == 416:
            # Server says our .part already covers the full range -- trust it.
            part_path.rename(dest_path)
            return "resumed, already complete"

        response.raise_for_status()

        resumed = response.status_code == 206
        mode = "ab" if resumed else "wb"
        if not resumed:
            resume_from = 0  # server ignored our Range header; starting over

        content_length = response.headers.get("content-length")
        total_bytes = (resume_from + int(content_length)) if content_length else None

        downloaded = resume_from
        last_print = 0.0
        with open(part_path, mode) as f:
            for chunk in response.iter_bytes(CHUNK_SIZE):
                f.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_print >= PROGRESS_INTERVAL_SECONDS:
                    _print_progress(dest_path.name, downloaded, total_bytes)
                    last_print = now
        _print_progress(dest_path.name, downloaded, total_bytes)
        sys.stdout.write("\n")

    part_path.rename(dest_path)
    return "resumed, downloaded" if resumed else "downloaded"


def download_with_retry(client: httpx.Client, url: str, dest_path: Path) -> str:
    delay = INITIAL_RETRY_DELAY_SECONDS
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _download_once(client, url, dest_path)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                return "skipped (404 -- URL likely stale, check the docs for a current link)"
            if status != 429 and status < 500:
                raise
            retry_after = exc.response.headers.get("retry-after")
            wait = float(retry_after) if retry_after else delay
            last_error: Exception = exc
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            wait = delay
            last_error = exc
            print(f"  connection error ({exc!r})")

        if attempt == MAX_RETRIES:
            raise last_error
        print(f"  waiting {wait:.0f}s before retry {attempt + 1}/{MAX_RETRIES}")
        time.sleep(wait)
        delay = min(delay * 2, MAX_RETRY_DELAY_SECONDS)

    raise RuntimeError(f"giving up on {url} after {MAX_RETRIES} attempts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help="Root directory to download into (default: <repo root>/data/bulk, regardless of cwd)",
    )
    parser.add_argument("--source", choices=["openfda", "dailymed", "all"], default="all")
    args = parser.parse_args()

    md_files = []
    if args.source in ("openfda", "all"):
        md_files.append(DOCS_DIR / "openfda_downloads.md")
    if args.source in ("dailymed", "all"):
        md_files.append(DOCS_DIR / "dailymed_download.md")

    urls = list(dict.fromkeys(u for md in md_files for u in extract_urls(md)))
    print(f"Found {len(urls)} file(s) across {len(md_files)} doc(s). Destination: {args.dest}/\n")

    results: dict[str, int] = {}
    with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
        for i, url in enumerate(urls, start=1):
            filename = url.rsplit("/", 1)[-1]
            dest_path = args.dest / bucket_for(url) / filename
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"[{i}/{len(urls)}] {dest_path.relative_to(args.dest)}")
            try:
                status = download_with_retry(client, url, dest_path)
            except Exception as exc:  # noqa: BLE001 -- report and keep going to the next file
                status = f"FAILED: {exc}"
                print(f"  {status} (partial file kept; re-run to resume)")
            else:
                print(f"  -> {status}")
            results[status] = results.get(status, 0) + 1

    print("\nSummary:")
    for status, count in sorted(results.items()):
        print(f"  {count:>3}  {status}")


if __name__ == "__main__":
    main()
