"""Request/response wire schemas for POST /api/check."""
from pydantic import BaseModel, Field

MAX_INGREDIENTS_TEXT_LENGTH = 5000


class CheckRequest(BaseModel):
    ingredients_text: str = Field(..., max_length=MAX_INGREDIENTS_TEXT_LENGTH)


class IngredientCheckResult(BaseModel):
    submitted_name: str
    matched_ingredient: str | None
    status: str
    reasoning: str | None
    citation: str | None
    confidence: float | None


class CheckResponse(BaseModel):
    results: list[IngredientCheckResult]
    summary: str
