"""The full AI pipeline (AI_PIPELINE.md, ROADMAP.md Brick 16): retrieve ->
prompt -> generate -> verify citations -> answer, with rejection/fallback
on validation failure (Section 7 point 4).

Two distinct places short-circuit to the "insufficient evidence" response
without trusting a possibly-fabricated LLM answer:

1. Retrieval returns nothing. No LLM call is made at all in this case --
   there's nothing to reason over, and calling the model with an empty
   evidence block would just invite it to answer from general knowledge,
   which Section 1 forbids outright.
2. Retrieval returns evidence, the model is asked, but its answer fails
   citation verification (`ai.citation.verify_citations`) -- an uncited or
   out-of-range claim. Per Section 7 point 4, the system is designed to
   prefer "I don't have evidence for that" over showing an unverified
   claim, so the raw model output is discarded, not shown to the user.

Not implemented: automatic regeneration with stricter constraints on
verification failure (Section 5 offers "regenerated ... or replaced with
an explicit insufficient-evidence response" as alternatives). A retry loop
adds a second non-deterministic LLM call that is materially harder to
test deterministically and doesn't change the safety property -- the
fallback response is already a correct, safe answer. Noted as a real,
deferred enhancement, not silently skipped.

There is also no pre-generation "low retrieval confidence" numeric gate
(Section 6 mentions surfacing "limited relevant evidence found" for low
retrieval confidence). `ts_rank` has no principled, query-independent
absolute scale to threshold against (Postgres's own documentation is
explicit that rank values are only meaningful for relative ordering within
a single query, not as an absolute cutoff) -- picking an arbitrary number
here would be exactly the kind of threshold-gaming this project has
explicitly refused to do elsewhere (see the Brick 11 fuzzy-match
threshold decision). The reliably decidable "no evidence" case -- zero
retrieval results -- is handled; a weak-but-nonempty result set is passed
to the model and lives or dies on citation verification like any other.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ai.citation import verify_citations
from ai.llm import generate
from ai.prompting import INSUFFICIENT_EVIDENCE_TEXT, SYSTEM_PROMPT, build_user_prompt
from ai.retrieval import Evidence, retrieve
from database.access.search import Provenance

DEFAULT_RETRIEVAL_LIMIT = 10


@dataclass(frozen=True)
class Reference:
    number: int
    entity_type: str
    entity_id: str
    source: Provenance


@dataclass(frozen=True)
class Answer:
    text: str
    references: list[Reference]
    insufficient_evidence: bool


def _fallback() -> Answer:
    return Answer(text=INSUFFICIENT_EVIDENCE_TEXT, references=[], insufficient_evidence=True)


def _references(evidence: list[Evidence], cited_numbers: frozenset[int]) -> list[Reference]:
    return [
        Reference(
            number=item.number,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            source=item.source,
        )
        for item in evidence
        if item.number in cited_numbers
    ]


def ask(
    session: Session, question: str, *, retrieval_limit: int = DEFAULT_RETRIEVAL_LIMIT
) -> Answer:
    evidence = retrieve(session, question, limit=retrieval_limit)
    if not evidence:
        return _fallback()

    raw_answer = generate(SYSTEM_PROMPT, build_user_prompt(question, evidence))
    stripped = raw_answer.strip()

    if stripped == INSUFFICIENT_EVIDENCE_TEXT:
        return _fallback()

    verification = verify_citations(raw_answer, len(evidence))
    if not verification.valid:
        return _fallback()

    return Answer(
        text=stripped,
        references=_references(evidence, verification.cited_numbers),
        insufficient_evidence=False,
    )
