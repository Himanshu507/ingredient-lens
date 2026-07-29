import json
from pathlib import Path
from typing import Any

from ingestion.openfda.adapter import fetch_and_parse_drug_labels
from ingestion.openfda.models import OpenFdaDrugLabelRecord

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "openfda"


def _load(name: str) -> dict[str, Any]:
    with (GOLDEN_DIR / name).open() as f:
        result: dict[str, Any] = json.load(f)
        return result


class _FakeResponse:
    def __init__(self, json_data: dict[str, Any]) -> None:
        self.status_code = 200
        self._json_data = json_data

    def json(self) -> dict[str, Any]:
        return self._json_data


class _FakeClient:
    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self._pages = list(pages)

    def get(self, url: str, params: dict[str, Any]) -> _FakeResponse:
        if not self._pages:
            return _FakeResponse({"results": []})
        return _FakeResponse({"results": self._pages.pop(0)})


def test_fetch_and_parse_streams_records_across_pages() -> None:
    otc = _load("drug_label_otc.json")
    boxed = _load("drug_label_boxed_warning.json")
    client = _FakeClient(pages=[[otc], [boxed]])

    records = list(fetch_and_parse_drug_labels(client, page_size=1))  # type: ignore[arg-type]

    assert len(records) == 2
    assert all(isinstance(r, OpenFdaDrugLabelRecord) for r in records)
    assert records[0].set_id == "0000025c-6dbf-4af7-a741-5cbacaed519a"
    assert records[1].brand_name == "Naproxen"
