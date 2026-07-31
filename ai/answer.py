"""The full AI pipeline (AI_PIPELINE.md, ROADMAP.md Brick 16): the model
drives its own retrieval via a `search_evidence` tool, then answers with
citations, verified before being trusted (Section 7 point 4).

This is a deliberate departure from AI_PIPELINE.md Section 7 point 5's
original wording ("no tool access for the model... query the database
directly") -- that constraint was written when retrieval was a single fixed
step run before the model ever saw the question. In practice, a fixed
single retrieval pass means a user who doesn't phrase their question as a
proper question (e.g. typing a bare product name like "Acetaminophen
Ibuprofen (NSAID)" into the ask box) gets "no relevant evidence found" even
when the underlying data has a clean answer -- the model never gets a
chance to reformulate the query itself. Real chat assistants solve this
with agentic tool-calling; this does the same, deliberately, with the
constraint narrowed rather than dropped: the model's only tool is a
read-only, parameterized search function (`ingestion` and raw source
payloads remain fully out of reach), calls are capped
(`MAX_TOOL_ITERATIONS`), and every final answer still goes through the same
mandatory citation verification as before. AI_PIPELINE.md Section 7 is
updated to describe this, not left stale.

Two places still short-circuit to the "insufficient evidence" response
without trusting a possibly-fabricated LLM answer:

1. The tool-call loop is exhausted (`MAX_TOOL_ITERATIONS`) without the
   model producing a final plain-text answer -- treated the same as "no
   evidence," not retried indefinitely.
2. The model's final answer fails citation verification
   (`ai.citation.verify_citations`) -- an uncited or out-of-range claim.
   The raw model output is discarded, never shown to the user.
"""

import json
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from ai.citation import verify_citations
from ai.llm import generate_with_tools
from ai.prompting import INSUFFICIENT_EVIDENCE_TEXT, TOOL_SYSTEM_PROMPT, build_evidence_block
from ai.retrieval import Evidence, retrieve
from database.access.search import Provenance

DEFAULT_RETRIEVAL_LIMIT = 10
MAX_TOOL_ITERATIONS = 4

SEARCH_EVIDENCE_TOOL = {
    "type": "function",
    "function": {
        "name": "search_evidence",
        "description": (
            "Search the canonical regulatory database for evidence about ingredients, "
            "products, warnings, or recalls. Call this one or more times with different "
            "keyword phrasings to gather evidence before answering -- this is keyword "
            "search, not natural-language question answering, so short, specific queries "
            "(e.g. 'acetaminophen liver warning', a product name) work best."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A keyword search query.",
                }
            },
            "required": ["query"],
        },
    },
}


@dataclass(frozen=True)
class Reference:
    number: int
    entity_type: str
    entity_id: str
    source: Provenance
    external_url: str | None


@dataclass(frozen=True)
class Answer:
    text: str
    references: list[Reference]
    insufficient_evidence: bool


def _fallback() -> Answer:
    return Answer(text=INSUFFICIENT_EVIDENCE_TEXT, references=[], insufficient_evidence=True)


class EvidenceRegistry:
    """Assigns each distinct piece of evidence a stable citation number the
    first time it's seen, across however many `search_evidence` calls the
    model makes in one conversation -- a second search that re-surfaces the
    same product/warning must cite it with the *same* number as the first
    time, not a new one, or the model's own citations would drift out of
    sync with what it already told the user.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], Evidence] = {}
        self._order: list[tuple[str, str]] = []

    def add(self, items: list[Evidence]) -> list[Evidence]:
        renumbered = []
        for item in items:
            key = (item.entity_type, item.entity_id)
            existing = self._by_key.get(key)
            if existing is not None:
                renumbered.append(existing)
                continue
            stable = replace(item, number=len(self._order) + 1)
            self._by_key[key] = stable
            self._order.append(key)
            renumbered.append(stable)
        return renumbered

    def all(self) -> list[Evidence]:
        return [self._by_key[key] for key in self._order]


def _references(evidence: list[Evidence], cited_numbers: frozenset[int]) -> list[Reference]:
    return [
        Reference(
            number=item.number,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            source=item.source,
            external_url=item.external_url,
        )
        for item in evidence
        if item.number in cited_numbers
    ]


def _run_search_tool(
    session: Session, registry: EvidenceRegistry, arguments: dict[str, object], *, limit: int
) -> str:
    query = str(arguments.get("query", "")).strip()
    if not query:
        return "No query provided."
    results = retrieve(session, query, limit=limit)
    numbered = registry.add(results)
    return build_evidence_block(numbered)


def ask(
    session: Session, question: str, *, retrieval_limit: int = DEFAULT_RETRIEVAL_LIMIT
) -> Answer:
    registry = EvidenceRegistry()
    messages: list[dict[str, object]] = [
        {"role": "system", "content": TOOL_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    final_text: str | None = None
    for _ in range(MAX_TOOL_ITERATIONS):
        result = generate_with_tools(messages, tools=[SEARCH_EVIDENCE_TOOL])

        if not result.tool_calls:
            final_text = result.content or ""
            break

        messages.append(
            {
                "role": "assistant",
                "content": result.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in result.tool_calls
                ],
            }
        )
        for tool_call in result.tool_calls:
            tool_output = _run_search_tool(
                session, registry, tool_call.arguments, limit=retrieval_limit
            )
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_output})

    if final_text is None:
        return _fallback()

    stripped = final_text.strip()
    if not stripped or stripped == INSUFFICIENT_EVIDENCE_TEXT:
        return _fallback()

    evidence = registry.all()
    verification = verify_citations(final_text, len(evidence))
    if not verification.valid:
        return _fallback()

    return Answer(
        text=stripped,
        references=_references(evidence, verification.cited_numbers),
        insufficient_evidence=False,
    )
