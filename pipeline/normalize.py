"""Stage 3 — messy rows -> structured, confidence-scored status via OpenAI.

Deep module: normalize_rows() hides the LLM call, the prompt, the category
legend, the confidence-flagging rule, and the idempotency cache (looked up in
the extraction_staging table, keyed by ingredient_name + input_hash) behind
one call. Callers never see the OpenAI client or the caching mechanics.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

import config
from db.models import ExtractionStaging
from db.session import get_session
from pipeline.parse import AgencyAction, IngredientRawRow

log = logging.getLogger(__name__)

# Section 2's category legend — hardcoded, never inferred.
CATEGORY_LEGEND: dict[int, str] = {
    1: "Subject of an authorized health claim or qualified health claim",
    2: "Subject of a safety communication",
    3: 'Not a "dietary ingredient" under FD&C Act §201(ff)(1)',
    4: "Excluded from the dietary supplement definition under FD&C Act §201(ff)(3)",
    5: "Dietary ingredient hasn't met the safety standard under FD&C Act §402(f)(1)(A)",
    6: "New dietary ingredient hasn't met the safety standard under FD&C Act §402(f)(1)(B)",
    7: "New dietary ingredient requiring premarket safety notification, none submitted, "
    "under FD&C Act §413(a)(2)",
}

NormalizedStatus = Literal[
    "permitted_with_claim",
    "caution_flagged",
    "not_a_dietary_ingredient",
    "excluded_from_definition",
    "safety_standard_unmet",
    "new_ingredient_unmet_safety",
    "premarket_notification_required",
]


class LLMNormalizationResult(BaseModel):
    normalized_status: NormalizedStatus
    reasoning: str
    confidence: float


class NormalizedIngredient(BaseModel):
    ingredient_name: str
    synonyms: list[str]
    category_codes: list[int]
    date_added: str | None
    actions: list[AgencyAction]
    normalized_status: str
    reasoning: str
    confidence: float
    needs_review: bool
    source_staging_id: int | None = None


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _input_hash(row: IngredientRawRow) -> str:
    payload = json.dumps(
        {"category_codes": row.category_codes, "actions": [a.model_dump() for a in row.actions]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_prompt(row: IngredientRawRow) -> str:
    legend_lines = "\n".join(f"{code}: {desc}" for code, desc in CATEGORY_LEGEND.items())
    actions_lines = (
        "\n".join(
            f"- {a.text}" + (f" ({a.date_text})" if a.date_text else "") for a in row.actions
        )
        or "(no agency actions listed)"
    )
    codes = ", ".join(str(c) for c in row.category_codes) or "(none)"
    return (
        "You are classifying a dietary supplement ingredient's FDA regulatory status.\n\n"
        f"FDA category legend:\n{legend_lines}\n\n"
        f"Ingredient: {row.ingredient_name}\n"
        f"FDA category codes for this ingredient: {codes}\n"
        f"Agency actions/statements:\n{actions_lines}\n\n"
        "Pick the single normalized_status that best reflects this ingredient's overall "
        "regulatory posture. If multiple category codes apply and they conflict in severity "
        "(e.g. a health claim alongside an exclusion from the supplement definition), do not "
        "flatten them into one generic reading -- choose the status for the most legally "
        "significant code and say so explicitly in your one-sentence reasoning. Ground "
        "reasoning only in the legend text and the agency actions above; do not speculate "
        "beyond them."
    )


def _call_llm(row: IngredientRawRow) -> LLMNormalizationResult:
    completion = _get_client().beta.chat.completions.parse(
        model=config.OPENAI_MODEL,
        messages=[{"role": "user", "content": _build_prompt(row)}],
        response_format=LLMNormalizationResult,
    )
    return completion.choices[0].message.parsed


def _normalize_one(session, row: IngredientRawRow) -> NormalizedIngredient:
    input_hash = _input_hash(row)
    staging = (
        session.query(ExtractionStaging)
        .filter_by(ingredient_name=row.ingredient_name, input_hash=input_hash)
        .one_or_none()
    )

    if staging is None:
        result = _call_llm(row)
        staging = ExtractionStaging(
            ingredient_name=row.ingredient_name,
            input_hash=input_hash,
            raw_input={
                "category_codes": row.category_codes,
                "actions": [a.model_dump() for a in row.actions],
            },
            normalized_status=result.normalized_status,
            reasoning=result.reasoning,
            confidence=result.confidence,
            needs_review=result.confidence < config.NORMALIZATION_CONFIDENCE_THRESHOLD,
        )
        session.add(staging)
        session.flush()
        log.info(
            "normalized %r via LLM -> %s (%.2f)",
            row.ingredient_name,
            staging.normalized_status,
            staging.confidence,
        )
    else:
        log.info("cache hit for %r, skipping LLM call", row.ingredient_name)

    return NormalizedIngredient(
        ingredient_name=row.ingredient_name,
        synonyms=row.synonyms,
        category_codes=row.category_codes,
        date_added=row.date_added,
        actions=row.actions,
        normalized_status=staging.normalized_status,
        reasoning=staging.reasoning,
        confidence=staging.confidence,
        needs_review=staging.needs_review,
        source_staging_id=staging.id,
    )


def normalize_rows(rows: list[IngredientRawRow]) -> list[NormalizedIngredient]:
    with get_session() as session:
        return [_normalize_one(session, row) for row in rows]


def save_json(rows: list[NormalizedIngredient], out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([r.model_dump() for r in rows], indent=2), encoding="utf-8")
    return out_path
