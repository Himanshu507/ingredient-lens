"""The entire backend matching surface: text in, per-ingredient status out.

Deep module: check_ingredients() hides candidate splitting and the
cheapest-first matching cascade (exact -> synonym -> fuzzy -> LLM last
resort) behind one call. Callers (the API endpoint, tests) never see the
individual tiers.
"""
from __future__ import annotations

import logging

from openai import OpenAI
from pydantic import BaseModel
from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

import config
from api.models import IngredientCheckResult
from db.models import Ingredient

log = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


class LLMMatchResult(BaseModel):
    matched_name: str | None


def split_candidates(ingredients_text: str) -> list[str]:
    """Split on commas/newlines, but not commas inside parens -- a label like
    "Artificial Flavours (Chocolate, Vanilla)" is one ingredient entry, not two.
    """
    candidates: list[str] = []
    current: list[str] = []
    depth = 0
    for char in ingredients_text:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char in ",\n" and depth == 0:
            candidates.append("".join(current))
            current = []
        else:
            current.append(char)
    candidates.append("".join(current))
    return [c.strip() for c in candidates if c.strip()]


def _exact_match(candidate: str, ingredients: list[Ingredient]) -> Ingredient | None:
    cand = candidate.strip().lower()
    return next((ing for ing in ingredients if ing.name.strip().lower() == cand), None)


def _synonym_match(candidate: str, ingredients: list[Ingredient]) -> Ingredient | None:
    cand = candidate.strip().lower()
    for ing in ingredients:
        if any(syn.strip().lower() == cand for syn in ing.synonyms):
            return ing
    return None


def _fuzzy_match(candidate: str, ingredients: list[Ingredient]) -> Ingredient | None:
    choices: dict[str, Ingredient] = {}
    for ing in ingredients:
        choices.setdefault(ing.name, ing)
        for syn in ing.synonyms:
            choices.setdefault(syn, ing)
    if not choices:
        return None

    best = process.extractOne(candidate, choices.keys(), scorer=fuzz.WRatio)
    if best is None:
        return None
    matched_name, score, _ = best
    if score < config.FUZZY_MATCH_SCORE_THRESHOLD:
        return None
    return choices[matched_name]


def _llm_match(candidate: str, ingredients: list[Ingredient]) -> Ingredient | None:
    names = sorted({ing.name for ing in ingredients})
    if not names:
        return None
    prompt = (
        "A user submitted this ingredient name, possibly noisy from OCR or informal "
        "labeling. Pick the single best matching name from the list below, or null if "
        "nothing plausibly matches -- do not guess.\n\n"
        f"Candidate: {candidate!r}\n\n"
        "Known ingredient names:\n" + "\n".join(f"- {n}" for n in names)
    )
    try:
        completion = _get_client().beta.chat.completions.parse(
            model=config.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format=LLMMatchResult,
        )
    except Exception:
        # Last-resort tier only -- an LLM outage/misconfiguration degrades this one
        # candidate to "no match" rather than failing the whole request.
        log.exception("LLM match fallback failed for %r", candidate)
        return None
    parsed = completion.choices[0].message.parsed
    if not parsed.matched_name:
        return None
    return next((ing for ing in ingredients if ing.name == parsed.matched_name), None)


def _resolve_candidate(candidate: str, ingredients: list[Ingredient]) -> Ingredient | None:
    return (
        _exact_match(candidate, ingredients)
        or _synonym_match(candidate, ingredients)
        or _fuzzy_match(candidate, ingredients)
        or _llm_match(candidate, ingredients)
    )


def _to_result(candidate: str, ingredient: Ingredient | None) -> IngredientCheckResult:
    if ingredient is None:
        return IngredientCheckResult(
            submitted_name=candidate,
            matched_ingredient=None,
            status="not_in_database",
            reasoning=None,
            citation=None,
            confidence=None,
        )

    status_row = next((s for s in ingredient.statuses if s.country_id == "US"), None)
    if status_row is None:
        return IngredientCheckResult(
            submitted_name=candidate,
            matched_ingredient=ingredient.name,
            status="not_in_database",
            reasoning=None,
            citation=None,
            confidence=None,
        )

    return IngredientCheckResult(
        submitted_name=candidate,
        matched_ingredient=ingredient.name,
        status=status_row.normalized_status,
        reasoning=status_row.reasoning,
        citation=status_row.citation_url,
        confidence=status_row.confidence,
    )


def check_ingredients(ingredients_text: str, session: Session) -> list[IngredientCheckResult]:
    candidates = split_candidates(ingredients_text)
    ingredients = session.query(Ingredient).all()
    return [
        _to_result(candidate, _resolve_candidate(candidate, ingredients))
        for candidate in candidates
    ]


def build_summary(results: list[IngredientCheckResult]) -> str:
    flagged = sum(1 for r in results if r.status not in ("permitted_with_claim", "not_in_database"))
    clear = sum(1 for r in results if r.status == "permitted_with_claim")
    missing = sum(1 for r in results if r.status == "not_in_database")
    return f"{flagged} flagged, {clear} clear, {missing} not FDA-flagged"
