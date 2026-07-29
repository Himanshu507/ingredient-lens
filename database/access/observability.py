"""Operational health views (OBSERVABILITY.md Section 5).

Built directly from `ingestion_logs`, `ingestion_dead_letters`, and
`entity_resolution_reviews` — no shadow analytics store; the operational
database already holds the ground truth these views need.

Not in scope here: per-resolution-strategy outcome ratios (auto-merge vs.
manual-review vs. new-entity counts, mentioned in OBSERVABILITY.md Section 3
and Section 5's trend view). That metric isn't derivable from the current
schema — resolve_entity() doesn't record which strategy matched a given
ingredient/manufacturer anywhere queryable, only the *fact* that a review
was queued (entity_resolution_reviews) or a product changed
(ingestion_logs). Adding it means instrumenting resolve_entity() itself,
which is a real, separate piece of work — noted rather than faked from data
that doesn't support it.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from database.models.dead_letter import IngestionDeadLetter
from database.models.entity_resolution_review import EntityResolutionReview
from database.models.enums import IngestionRunStatus, ReviewStatus
from database.models.ingestion_log import IngestionLog


@dataclass(frozen=True)
class LastRun:
    run_id: str
    status: str
    started_at: str
    completed_at: str | None
    records_fetched: int
    records_created: int
    records_updated: int
    records_unchanged: int
    records_rejected: int


@dataclass(frozen=True)
class SourceHealth:
    source: str
    last_run: LastRun | None
    success_rate_7d: float | None
    success_rate_30d: float | None
    dead_letter_count_7d: int
    dead_letter_rate_7d: float | None


def _success_rate(session: Session, source: str, since: datetime) -> float | None:
    total = session.execute(
        sa.select(sa.func.count())
        .select_from(IngestionLog)
        .where(IngestionLog.source == source, IngestionLog.started_at >= since)
    ).scalar_one()
    if total == 0:
        return None
    completed = session.execute(
        sa.select(sa.func.count())
        .select_from(IngestionLog)
        .where(
            IngestionLog.source == source,
            IngestionLog.started_at >= since,
            IngestionLog.status == IngestionRunStatus.COMPLETED,
        )
    ).scalar_one()
    return completed / total


def get_source_health(session: Session, source: str) -> SourceHealth:
    """Answers "is source X healthy" (ROADMAP.md Brick 14's done-when) without
    a hand-written SQL query: last run's outcome, trailing success rates,
    trailing DLQ volume.
    """
    now = datetime.now(UTC)

    last_run_row = session.execute(
        sa.select(IngestionLog)
        .where(IngestionLog.source == source)
        .order_by(IngestionLog.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    last_run = None
    if last_run_row is not None:
        last_run = LastRun(
            run_id=last_run_row.run_id,
            status=last_run_row.status.value,
            started_at=last_run_row.started_at.isoformat(),
            completed_at=(
                last_run_row.completed_at.isoformat() if last_run_row.completed_at else None
            ),
            records_fetched=last_run_row.records_fetched,
            records_created=last_run_row.records_created,
            records_updated=last_run_row.records_updated,
            records_unchanged=last_run_row.records_unchanged,
            records_rejected=last_run_row.records_rejected,
        )

    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    fetched_7d = session.execute(
        sa.select(sa.func.coalesce(sa.func.sum(IngestionLog.records_fetched), 0)).where(
            IngestionLog.source == source, IngestionLog.started_at >= since_7d
        )
    ).scalar_one()
    dlq_7d = session.execute(
        sa.select(sa.func.count())
        .select_from(IngestionDeadLetter)
        .where(IngestionDeadLetter.source == source, IngestionDeadLetter.created_at >= since_7d)
    ).scalar_one()

    return SourceHealth(
        source=source,
        last_run=last_run,
        success_rate_7d=_success_rate(session, source, since_7d),
        success_rate_30d=_success_rate(session, source, since_30d),
        dead_letter_count_7d=dlq_7d,
        dead_letter_rate_7d=(dlq_7d / fetched_7d) if fetched_7d else None,
    )


@dataclass(frozen=True)
class DailyTrend:
    date: str
    records_fetched: int
    records_rejected: int
    validation_failure_rate: float | None
    dead_letter_count: int
    reviews_queued: int


def get_trend(session: Session, source: str, *, days: int = 30) -> list[DailyTrend]:
    """Day-by-day drift (OBSERVABILITY.md Section 5's trend view) — a single
    run's log would never surface a slow rise in validation failures or DLQ
    volume; this bucket-by-day view does.

    `reviews_queued` is a system-wide count, not scoped to `source`:
    `entity_resolution_reviews` has no source column (a review is about two
    candidate entities, not a specific ingestion run).
    """
    since = datetime.now(UTC) - timedelta(days=days)
    day = sa.cast(IngestionLog.started_at, sa.Date)

    log_rows = session.execute(
        sa.select(
            day.label("day"),
            sa.func.coalesce(sa.func.sum(IngestionLog.records_fetched), 0),
            sa.func.coalesce(sa.func.sum(IngestionLog.records_rejected), 0),
        )
        .where(IngestionLog.source == source, IngestionLog.started_at >= since)
        .group_by(day)
    ).all()

    dlq_day = sa.cast(IngestionDeadLetter.created_at, sa.Date)
    dlq_by_day: dict[date, int] = dict(
        session.execute(
            sa.select(dlq_day, sa.func.count())
            .where(IngestionDeadLetter.source == source, IngestionDeadLetter.created_at >= since)
            .group_by(dlq_day)
        )
        .tuples()
        .all()
    )

    review_day = sa.cast(EntityResolutionReview.created_at, sa.Date)
    reviews_by_day: dict[date, int] = dict(
        session.execute(
            sa.select(review_day, sa.func.count())
            .where(EntityResolutionReview.created_at >= since)
            .group_by(review_day)
        )
        .tuples()
        .all()
    )

    trends = [
        DailyTrend(
            date=day_value.isoformat(),
            records_fetched=fetched,
            records_rejected=rejected,
            validation_failure_rate=(rejected / fetched) if fetched else None,
            dead_letter_count=dlq_by_day.get(day_value, 0),
            reviews_queued=reviews_by_day.get(day_value, 0),
        )
        for day_value, fetched, rejected in log_rows
    ]
    return sorted(trends, key=lambda t: t.date)


@dataclass(frozen=True)
class EntityResolutionHealth:
    pending_count: int
    oldest_pending_age_hours: float | None
    approved_count: int
    rejected_count: int


def get_entity_resolution_health(session: Session) -> EntityResolutionHealth:
    """Answers "what's the manual review backlog" (ROADMAP.md Brick 14's
    done-when): queue size and age are the two signals ENTITY_RESOLUTION.md
    Section 7 calls out as tracked operational metrics.
    """
    pending_count = session.execute(
        sa.select(sa.func.count())
        .select_from(EntityResolutionReview)
        .where(EntityResolutionReview.status == ReviewStatus.PENDING)
    ).scalar_one()

    oldest_pending = session.execute(
        sa.select(sa.func.min(EntityResolutionReview.created_at)).where(
            EntityResolutionReview.status == ReviewStatus.PENDING
        )
    ).scalar_one()
    oldest_pending_age_hours = None
    if oldest_pending is not None:
        oldest_pending_age_hours = (datetime.now(UTC) - oldest_pending).total_seconds() / 3600

    approved_count = session.execute(
        sa.select(sa.func.count())
        .select_from(EntityResolutionReview)
        .where(EntityResolutionReview.status == ReviewStatus.APPROVED)
    ).scalar_one()
    rejected_count = session.execute(
        sa.select(sa.func.count())
        .select_from(EntityResolutionReview)
        .where(EntityResolutionReview.status == ReviewStatus.REJECTED)
    ).scalar_one()

    return EntityResolutionHealth(
        pending_count=pending_count,
        oldest_pending_age_hours=oldest_pending_age_hours,
        approved_count=approved_count,
        rejected_count=rejected_count,
    )
