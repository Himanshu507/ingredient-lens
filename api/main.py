"""FastAPI app. One route: POST /api/check. Text in, only ever text -- no
image handling here at all, so a product photo never reaches the backend.
"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from api.match import build_summary, check_ingredients
from api.models import CheckRequest, CheckResponse
from db.session import get_db

app = FastAPI(title="ingredient-lens API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


@app.get("/")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/check", response_model=CheckResponse)
def check(
    request: CheckRequest, session: Session = Depends(get_db)  # noqa: B008
) -> CheckResponse:
    results = check_ingredients(request.ingredients_text, session)
    return CheckResponse(results=results, summary=build_summary(results))
