from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_session
from database.access.observability import (
    DailyTrend,
    EntityResolutionHealth,
    SourceHealth,
    get_entity_resolution_health,
    get_source_health,
    get_trend,
)

router = APIRouter(prefix="/observability")


@router.get("/sources/{source}/health", response_model=SourceHealth)
def source_health(source: str, session: Session = Depends(get_session)) -> SourceHealth:
    return get_source_health(session, source)


@router.get("/sources/{source}/trend", response_model=list[DailyTrend])
def source_trend(
    source: str,
    days: int = Query(30, ge=1, le=365),
    session: Session = Depends(get_session),
) -> list[DailyTrend]:
    return get_trend(session, source, days=days)


@router.get("/entity-resolution/health", response_model=EntityResolutionHealth)
def entity_resolution_health(session: Session = Depends(get_session)) -> EntityResolutionHealth:
    return get_entity_resolution_health(session)
