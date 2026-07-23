from pathlib import Path

import pytest

from pipeline.parse import parse_html

_FIXTURE_HTML = """
<html><body>
<table>
<thead><tr>
  <th>Ingredients</th><th>Other Known Names</th>
  <th>Agency Actions/Statements</th><th>Category</th><th>Date</th>
</tr></thead>
<tbody>
<tr>
  <td>1,4 DMAA</td>
  <td><p>1,4-dimethylamylamine</p><p>1,4-dimethylpentylamine</p></td>
  <td>
    <p><a href="/drugs/example-safety">Safety Communication</a> (December 2023)</p>
    <p><a href="https://www.fda.gov/absolute/example">Voluntary Recall</a> (May 2021)</p>
  </td>
  <td><a href="#category3">3</a></td>
  <td>2023/04</td>
</tr>
<tr>
  <td><i>Ephedra sinica</i></td>
  <td><p>N/A</p></td>
  <td><p><a href="/example-multi">Multi-category action</a></p></td>
  <td><p><a href="#category2">2</a>, <a href="#category6">6</a></p></td>
  <td>2025/12</td>
</tr>
<tr>
  <td>Malformed Row</td>
  <td>only one cell</td>
</tr>
</tbody>
</table>
</body></html>
"""


@pytest.fixture()
def html_path(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.html"
    path.write_text(_FIXTURE_HTML, encoding="utf-8")
    return path


def test_parses_multiline_synonyms_and_actions_with_absolute_urls(html_path: Path):
    rows = parse_html(html_path)

    dmaa = rows[0]
    assert dmaa.ingredient_name == "1,4 DMAA"
    assert dmaa.synonyms == ["1,4-dimethylamylamine", "1,4-dimethylpentylamine"]
    assert dmaa.category_codes == [3]
    assert dmaa.date_added == "2023/04"

    assert len(dmaa.actions) == 2
    assert dmaa.actions[0].text == "Safety Communication"
    assert dmaa.actions[0].url == "https://www.fda.gov/drugs/example-safety"
    assert dmaa.actions[0].date_text == "December 2023"
    # already-absolute URLs pass through unchanged
    assert dmaa.actions[1].url == "https://www.fda.gov/absolute/example"


def test_italicized_name_and_na_synonym_and_multi_category(html_path: Path):
    rows = parse_html(html_path)

    ephedra = rows[1]
    assert ephedra.ingredient_name == "Ephedra sinica"
    assert ephedra.synonyms == []  # "N/A" dropped, never a literal synonym
    assert ephedra.category_codes == [2, 6]


def test_malformed_row_is_skipped_not_silently_dropped_from_return_shape(html_path: Path):
    rows = parse_html(html_path)
    # 3 rows in the fixture, 1 malformed (only 2 cells) -> skipped, not raised
    assert len(rows) == 2
    assert all(r.ingredient_name != "Malformed Row" for r in rows)
