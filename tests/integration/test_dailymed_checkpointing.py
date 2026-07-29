from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.models.enums import IngestionRunStatus
from database.models.ingestion_log import IngestionLog
from database.models.product import Product
from ingestion.dailymed.extraction import SplPackage
from ingestion.dailymed.run import find_resumable_run, ingest_spl_documents

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "dailymed"


def _package(name: str) -> SplPackage:
    return SplPackage(package_name=name, xml_bytes=(GOLDEN_DIR / name).read_bytes())


def _five_packages() -> list[SplPackage]:
    """Five distinct, valid packages, built from three real documents plus
    two synthetically-renamed duplicates of the OTC one (distinct package
    identifiers, distinct set_ids via a byte-level swap, still real SPL
    content)."""
    otc_xml = (GOLDEN_DIR / "otc_liquid_bandage.xml").read_bytes()
    variants = []
    for i, fake_set_id in enumerate(["11111111-1111-1111-1111-111111111111", "222222"]):
        variant_xml = otc_xml.replace(b"036fd504-0cda-60ab-e063-6394a90a2f18", fake_set_id.encode())
        variants.append(SplPackage(package_name=f"synthetic_{i}.zip", xml_bytes=variant_xml))

    return [
        _package("animal_injection.xml"),
        _package("human_rx_injection.xml"),
        _package("otc_liquid_bandage.xml"),
        *variants,
    ]


class _CrashAfterN:
    def __init__(self, packages: list[SplPackage], crash_after: int) -> None:
        self._packages = packages
        self._crash_after = crash_after

    def __iter__(self) -> Iterator[SplPackage]:
        for i, package in enumerate(self._packages):
            if i == self._crash_after:
                raise RuntimeError("simulated mid-run crash")
            yield package


def _count(session: Session, model: type) -> int:
    return session.execute(sa.select(sa.func.count()).select_from(model)).scalar_one()


def test_mid_run_failure_leaves_a_resumable_partial_log(db_session: Session) -> None:
    packages = _five_packages()

    with pytest.raises(RuntimeError, match="simulated mid-run crash"):
        ingest_spl_documents(
            db_session, _CrashAfterN(packages, crash_after=3), checkpoint_batch_size=1
        )

    resumable = find_resumable_run(db_session, source="dailymed", endpoint="spl")
    assert resumable is not None
    assert resumable.status == IngestionRunStatus.PARTIAL
    assert resumable.checkpoint_state is not None
    assert len(resumable.checkpoint_state["completed_packages"]) == 3
    assert _count(db_session, Product) == 3


def test_resume_completes_without_reprocessing_or_duplicating(db_session: Session) -> None:
    packages = _five_packages()

    with pytest.raises(RuntimeError):
        ingest_spl_documents(
            db_session, _CrashAfterN(packages, crash_after=3), checkpoint_batch_size=1
        )

    log = ingest_spl_documents(db_session, packages, checkpoint_batch_size=1)

    assert log.status == IngestionRunStatus.COMPLETED
    assert log.records_fetched == 5
    assert log.records_created == 5
    assert log.checkpoint_state is not None
    assert len(log.checkpoint_state["completed_packages"]) == 5

    assert _count(db_session, Product) == 5

    logs_for_run = db_session.execute(
        sa.select(sa.func.count())
        .select_from(IngestionLog)
        .where(IngestionLog.run_id == log.run_id)
    ).scalar_one()
    assert logs_for_run == 1
