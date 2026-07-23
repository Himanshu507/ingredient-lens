"""Stage 2 — raw FDA HTML -> messy structured rows. Doesn't guess regulatory status.

Deep module: parse_html() hides all the real messiness (multi-line <br> cells,
italicized names, N/A synonyms, multiple category codes, non-fda.gov links)
behind one call. Downstream stages import IngredientRawRow/AgencyAction from
here rather than a separate shared-schemas file — this module owns the shape
of "what Stage 1's HTML actually contains."
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag
from pydantic import BaseModel

log = logging.getLogger(__name__)

_FDA_BASE_URL = "https://www.fda.gov"
_TRAILING_PAREN_RE = re.compile(r"\(([^()]+)\)\s*$")


class AgencyAction(BaseModel):
    text: str
    url: str | None = None
    date_text: str | None = None


class IngredientRawRow(BaseModel):
    ingredient_name: str
    synonyms: list[str] = []
    actions: list[AgencyAction] = []
    category_codes: list[int] = []
    date_added: str | None = None


def _split_by_br(cell: Tag) -> list[list]:
    """Group a cell's child nodes into lines, splitting on <br> tags."""
    groups: list[list] = [[]]
    for child in cell.contents:
        if isinstance(child, Tag) and child.name == "br":
            groups.append([])
        else:
            groups[-1].append(child)
    return [g for g in groups if g]


def _split_cell_into_lines(cell: Tag) -> list[list]:
    """Group a cell's content into lines.

    The live page wraps each entry in its own <p>; older dumps/fixtures may
    instead use <br>-separated content within a single block. Fall back to
    the whole cell as one line if neither is present.
    """
    paragraphs = cell.find_all("p", recursive=False)
    if paragraphs:
        return [list(p.contents) for p in paragraphs]
    if cell.find("br"):
        return _split_by_br(cell)
    return [list(cell.contents)]


def _node_text(node) -> str:
    if isinstance(node, NavigableString):
        return str(node).strip()
    return node.get_text(strip=True)


def _parse_synonyms(cell: Tag) -> list[str]:
    synonyms = []
    for group in _split_cell_into_lines(cell):
        text = " ".join(_node_text(n) for n in group).strip()
        if text and text.upper() != "N/A":
            synonyms.append(text)
    return synonyms


def _parse_actions(cell: Tag) -> list[AgencyAction]:
    actions = []
    for group in _split_cell_into_lines(cell):
        link = next((n for n in group if isinstance(n, Tag) and n.name == "a"), None)
        trailing_text = " ".join(
            _node_text(n) for n in group if n is not link and _node_text(n)
        ).strip()
        date_match = _TRAILING_PAREN_RE.search(trailing_text)
        href = link.get("href") if link else None
        actions.append(
            AgencyAction(
                text=link.get_text(strip=True) if link else trailing_text,
                url=urljoin(_FDA_BASE_URL, href) if href else None,
                date_text=date_match.group(1) if date_match else None,
            )
        )
    return actions


def _parse_category_codes(cell: Tag) -> list[int]:
    text = cell.get_text(strip=True)
    return [int(c.strip()) for c in text.split(",") if c.strip()]


def parse_html(html_path: str | Path) -> list[IngredientRawRow]:
    html = Path(html_path).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ValueError(f"no <table> found in {html_path}")

    tbody = table.find("tbody")
    body_rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

    rows = []
    for tr in body_rows:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 5:
            log.warning(
                "skipping malformed row (only %d cells): %r",
                len(cells),
                tr.get_text(strip=True)[:80],
            )
            continue
        name_cell, synonyms_cell, actions_cell, category_cell, date_cell = cells[:5]
        rows.append(
            IngredientRawRow(
                ingredient_name=name_cell.get_text(strip=True),
                synonyms=_parse_synonyms(synonyms_cell),
                actions=_parse_actions(actions_cell),
                category_codes=_parse_category_codes(category_cell),
                date_added=date_cell.get_text(strip=True) or None,
            )
        )
    return rows


def save_json(rows: list[IngredientRawRow], out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([r.model_dump() for r in rows], indent=2), encoding="utf-8")
    return out_path
