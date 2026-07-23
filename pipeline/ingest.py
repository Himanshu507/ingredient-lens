"""Stage 1 — fetch the live FDA page and save it untouched, before any parsing.

Deep module: one entrypoint hides the HTTP client setup, User-Agent, timestamped
filename, and the fail-loud-on-non-200 behavior.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import httpx

import config

_USER_AGENT = (
    "ingredient-lens/0.1 (proof-of-work regulatory data project; "
    "contact: https://github.com/Himanshu507/ingredient-lens) single-request static-page fetch"
)


def fetch_and_save(
    url: str = config.FDA_SOURCE_URL, out_dir: str | Path = config.RAW_HTML_DIR
) -> Path:
    """Fetch `url`, save the raw HTML untouched, return the saved path.

    Raises on a non-200 response — never silently produces an empty parse.
    """
    response = httpx.get(
        url, headers={"User-Agent": _USER_AGENT}, timeout=30.0, follow_redirects=True
    )
    response.raise_for_status()

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.date.today().isoformat()
    out_path = out_dir / f"fda_ingredient_directory_{timestamp}.html"
    out_path.write_text(response.text, encoding="utf-8")
    return out_path
