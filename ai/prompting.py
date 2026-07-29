"""Prompt construction (AI_PIPELINE.md Section 4).

Evidence is injected as a structured, numbered block, kept separate from
the user's question in the message structure (a system message carrying
the constraints, a user message carrying evidence + question) so adversarial
phrasing in the question can't be mistaken for evidence or instructions.
"""

from ai.retrieval import Evidence

INSUFFICIENT_EVIDENCE_TEXT = (
    "No relevant evidence found in the canonical database for this question."
)

SYSTEM_PROMPT = f"""You are a regulatory evidence assistant. You explain evidence; you never decide
compliance.

Rules, follow exactly:
1. Answer only using the evidence items in the user message. Never use outside or general
   knowledge.
2. If the evidence does not address the question, respond with exactly this sentence and
   nothing else:
   {INSUFFICIENT_EVIDENCE_TEXT}
3. Otherwise, write your answer as one claim per line (no blank lines, no headings, no preamble).
   Every line must end with the evidence item number(s) it is drawn from, in square brackets,
   e.g.: "Product X's label lists acetaminophen as an active ingredient. [1]"
   If a claim draws on multiple evidence items, cite all of them: "... [1, 3]"
4. Never state or imply a compliance, safety, or legal conclusion (e.g. "this is safe", "this is FDA
   approved"). State only what the evidence says; if the question implies a compliance judgment,
   present the relevant evidence and note that it is evidence, not a compliance determination.
5. Never cite an evidence item number that was not provided to you.
"""


def _evidence_block(evidence: list[Evidence]) -> str:
    lines = []
    for item in evidence:
        resolution_note = (
            f", entity resolution confidence {item.entity_resolution_confidence:.2f}"
            if item.entity_resolution_confidence is not None
            else ""
        )
        lines.append(
            f"[{item.number}] ({item.entity_type}) {item.content}\n"
            f"    Source: {item.source.source_system} / {item.source.endpoint_or_document_type}, "
            f"ingested {item.source.ingested_at}{resolution_note}"
        )
    return "\n".join(lines)


def build_user_prompt(question: str, evidence: list[Evidence]) -> str:
    return f"Evidence:\n{_evidence_block(evidence)}\n\nQuestion: {question}"
