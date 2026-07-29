import re

_WHITESPACE_RE = re.compile(r"\s+")
_DASH_VARIANTS = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-"})


def normalize_name(name: str) -> str:
    """Case-fold, collapse whitespace, normalize punctuation — deterministic
    and source-agnostic (ENTITY_RESOLUTION.md Section 3). Never consults the
    database and never makes a "same or different" judgment; it only produces
    the canonical string representation that matching (resolution/) operates on.

    Used for both ingredient and manufacturer names — Section 8 notes
    manufacturer resolution follows the identical pipeline, just at smaller scale.
    """
    text = name.strip().lower()
    text = text.translate(_DASH_VARIANTS)
    text = _WHITESPACE_RE.sub(" ", text)
    return text
