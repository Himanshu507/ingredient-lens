from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_session
from database.access.search import ProductHit, search_products

router = APIRouter()


@router.get("/products", response_model=list[ProductHit])
def list_products(
    q: str = Query(..., min_length=1, description="Keyword search query"),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[ProductHit]:
    return search_products(session, q, limit=limit)
