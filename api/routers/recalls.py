from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_session
from database.access.search import RecallHit, search_recalls

router = APIRouter()


@router.get("/recalls", response_model=list[RecallHit])
def list_recalls(
    q: str = Query(..., min_length=1, description="Keyword search query"),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[RecallHit]:
    return search_recalls(session, q, limit=limit)
