"""Deterministic citation verification (AI_PIPELINE.md Section 5, Section 7 point 3).

The LLM's output is not trusted verbatim. It is contractually required (by
the system prompt in `ai.prompting`) to write one claim per non-empty line,
each ending with the evidence item number(s) it draws from in square
brackets -- e.g. "This product lists acetaminophen as an active
ingredient. [1]". This module checks that contract mechanically: every
non-empty line must carry at least one citation marker, and every cited
number must refer to an evidence item that actually exists. Nothing here
calls an LLM or depends on non-deterministic output -- per TESTING_STRATEGY.md
Section 7, this is "fully deterministic application code, unit tested like
any other validation logic."

A line with no citation, or a citation number outside the evidence range,
fails the whole answer -- there is no partial-credit mode, per
AI_PIPELINE.md Section 5: "an answer with an uncited factual claim is
treated as a defect."
"""

import re
from dataclasses import dataclass

_CITATION_GROUP = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass(frozen=True)
class CitationVerificationResult:
    valid: bool
    cited_numbers: frozenset[int]
    reason: str | None


def verify_citations(answer_text: str, evidence_count: int) -> CitationVerificationResult:
    """Every non-empty line of `answer_text` must cite at least one evidence
    number in `1..evidence_count`. Returns the full set of numbers actually
    cited so the caller can build concrete references (Section 5) only for
    evidence the model actually used.
    """
    stripped = answer_text.strip()
    if not stripped:
        return CitationVerificationResult(
            valid=False, cited_numbers=frozenset(), reason="empty answer"
        )

    cited_numbers: set[int] = set()
    for line in (line.strip() for line in stripped.splitlines()):
        if not line:
            continue
        markers = _CITATION_GROUP.findall(line)
        if not markers:
            return CitationVerificationResult(
                valid=False,
                cited_numbers=frozenset(cited_numbers),
                reason=f"uncited claim: {line!r}",
            )
        for group in markers:
            for number_str in group.split(","):
                number = int(number_str.strip())
                if not 1 <= number <= evidence_count:
                    return CitationVerificationResult(
                        valid=False,
                        cited_numbers=frozenset(cited_numbers),
                        reason=(
                            f"citation [{number}] out of range "
                            f"(evidence has {evidence_count} item(s))"
                        ),
                    )
                cited_numbers.add(number)

    return CitationVerificationResult(
        valid=True, cited_numbers=frozenset(cited_numbers), reason=None
    )
