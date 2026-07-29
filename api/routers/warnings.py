from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_session
from database.access.search import WarningHit, search_warnings

router = APIRouter()


@router.get("/warnings", response_model=list[WarningHit])
def list_warnings(
    q: str = Query(..., min_length=1, description="Keyword search query"),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[WarningHit]:
    return search_warnings(session, q, limit=limit)
