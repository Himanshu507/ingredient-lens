from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.deps import get_session
from api.main import app
from database.access.observability import (
    get_entity_resolution_health,
    get_source_health,
    get_trend,
)
from database.models.dead_letter import IngestionDeadLetter
from database.models.entity_resolution_review import EntityResolutionReview
from database.models.enums import DeadLetterStage, EntityType, IngestionRunStatus, ReviewStatus
from database.models.ingestion_log import IngestionLog


def _make_log(
    session: Session,
    *,
    source: str = "openfda",
    status: IngestionRunStatus = IngestionRunStatus.COMPLETED,
    started_at: datetime,
    records_fetched: int = 10,
    records_rejected: int = 0,
) -> IngestionLog:
    log = IngestionLog(
        source=source,
        run_id=f"run-{started_at.isoformat()}",
        status=status,
        records_fetched=records_fetched,
        records_validated=records_fetched - records_rejected,
        records_created=records_fetched - records_rejected,
        records_updated=0,
        records_unchanged=0,
        records_rejected=records_rejected,
        started_at=started_at,
        completed_at=started_at + timedelta(minutes=5),
    )
    session.add(log)
    session.flush()
    return log


def test_get_source_health_reports_last_run_and_success_rates(db_session: Session) -> None:
    now = datetime.now(UTC)
    _make_log(db_session, started_at=now - timedelta(days=10), status=IngestionRunStatus.FAILED)
    _make_log(db_session, started_at=now - timedelta(hours=1))

    health = get_source_health(db_session, "openfda")

    assert health.source == "openfda"
    assert health.last_run is not None
    assert health.last_run.status == "completed"
    # 30d window includes both runs (1 of 2 completed); 7d window only the recent one.
    assert health.success_rate_30d == 0.5
    assert health.success_rate_7d == 1.0


def test_get_source_health_no_runs_returns_none_rates(db_session: Session) -> None:
    health = get_source_health(db_session, "dailymed")

    assert health.last_run is None
    assert health.success_rate_7d is None
    assert health.success_rate_30d is None
    assert health.dead_letter_rate_7d is None


def test_get_source_health_counts_dead_letters(db_session: Session) -> None:
    now = datetime.now(UTC)
    _make_log(db_session, started_at=now - timedelta(hours=1), records_fetched=20)
    db_session.add(
        IngestionDeadLetter(
            source="openfda",
            run_id="run-1",
            stage=DeadLetterStage.VALIDATION,
            record_identifier="rec-1",
            raw_payload={"bad": True},
            error_message="missing required field",
            created_at=now - timedelta(hours=1),
        )
    )
    db_session.flush()

    health = get_source_health(db_session, "openfda")

    assert health.dead_letter_count_7d == 1
    assert health.dead_letter_rate_7d == 1 / 20


def test_get_trend_buckets_by_day(db_session: Session) -> None:
    now = datetime.now(UTC)
    today = now.replace(hour=12, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    _make_log(db_session, started_at=today, records_fetched=10, records_rejected=2)
    _make_log(db_session, started_at=yesterday, records_fetched=5, records_rejected=0)
    db_session.add(
        IngestionDeadLetter(
            source="openfda",
            run_id="run-1",
            stage=DeadLetterStage.SAVE,
            record_identifier=None,
            raw_payload={},
            error_message="db error",
            created_at=today,
        )
    )
    db_session.add(
        EntityResolutionReview(
            entity_type=EntityType.INGREDIENT,
            candidate_a_id="1",
            candidate_b_id="2",
            confidence_score=0.8,
            created_at=today,
        )
    )
    db_session.flush()

    trend = get_trend(db_session, "openfda", days=30)

    assert [t.date for t in trend] == [yesterday.date().isoformat(), today.date().isoformat()]
    today_bucket = trend[1]
    assert today_bucket.records_fetched == 10
    assert today_bucket.records_rejected == 2
    assert today_bucket.validation_failure_rate == 0.2
    assert today_bucket.dead_letter_count == 1
    assert today_bucket.reviews_queued == 1

    yesterday_bucket = trend[0]
    assert yesterday_bucket.dead_letter_count == 0
    assert yesterday_bucket.reviews_queued == 0


def test_get_trend_empty_when_no_logs(db_session: Session) -> None:
    assert get_trend(db_session, "openfda") == []


def test_get_entity_resolution_health_counts_by_status(db_session: Session) -> None:
    now = datetime.now(UTC)
    db_session.add(
        EntityResolutionReview(
            entity_type=EntityType.INGREDIENT,
            candidate_a_id="1",
            candidate_b_id="2",
            confidence_score=0.8,
            status=ReviewStatus.PENDING,
            created_at=now - timedelta(hours=5),
        )
    )
    db_session.add(
        EntityResolutionReview(
            entity_type=EntityType.INGREDIENT,
            candidate_a_id="3",
            candidate_b_id="4",
            confidence_score=0.85,
            status=ReviewStatus.PENDING,
            created_at=now - timedelta(hours=1),
        )
    )
    db_session.add(
        EntityResolutionReview(
            entity_type=EntityType.MANUFACTURER,
            candidate_a_id="5",
            candidate_b_id="6",
            confidence_score=0.9,
            status=ReviewStatus.APPROVED,
            created_at=now - timedelta(days=1),
        )
    )
    db_session.add(
        EntityResolutionReview(
            entity_type=EntityType.MANUFACTURER,
            candidate_a_id="7",
            candidate_b_id="8",
            confidence_score=0.78,
            status=ReviewStatus.REJECTED,
            created_at=now - timedelta(days=1),
        )
    )
    db_session.flush()

    health = get_entity_resolution_health(db_session)

    assert health.pending_count == 2
    assert health.approved_count == 1
    assert health.rejected_count == 1
    assert health.oldest_pending_age_hours is not None
    assert 4.9 < health.oldest_pending_age_hours < 5.1


def test_get_entity_resolution_health_no_pending_reviews(db_session: Session) -> None:
    health = get_entity_resolution_health(db_session)

    assert health.pending_count == 0
    assert health.oldest_pending_age_hours is None


def test_observability_endpoints_reachable_over_http(db_session: Session) -> None:
    now = datetime.now(UTC)
    _make_log(db_session, started_at=now - timedelta(hours=1))
    db_session.add(
        EntityResolutionReview(
            entity_type=EntityType.INGREDIENT,
            candidate_a_id="1",
            candidate_b_id="2",
            confidence_score=0.8,
            created_at=now,
        )
    )
    db_session.flush()

    app.dependency_overrides[get_session] = lambda: db_session
    try:
        client = TestClient(app)
        health_response = client.get("/observability/sources/openfda/health")
        trend_response = client.get("/observability/sources/openfda/trend", params={"days": 7})
        resolution_response = client.get("/observability/entity-resolution/health")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert health_response.status_code == 200
    assert health_response.json()["source"] == "openfda"

    assert trend_response.status_code == 200
    assert len(trend_response.json()) == 1

    assert resolution_response.status_code == 200
    assert resolution_response.json()["pending_count"] == 1
