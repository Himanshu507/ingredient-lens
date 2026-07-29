from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_session
from database.access.search import IngredientHit, search_ingredients

router = APIRouter()


@router.get("/ingredients", response_model=list[IngredientHit])
def list_ingredients(
    q: str = Query(..., min_length=1, description="Keyword search query"),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[IngredientHit]:
    return search_ingredients(session, q, limit=limit)
