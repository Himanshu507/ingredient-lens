import json
import zipfile
from pathlib import Path
from typing import Any

from ingestion.openfda.bulk_adapter import fetch_and_parse_bulk_partition
from ingestion.openfda.bulk_manifest import BulkPartition
from ingestion.openfda.models import OpenFdaDrugLabelRecord

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "openfda"


class _FakeStreamResponse:
    def __init__(self, status_code: int, chunks: list[bytes]) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.headers: dict[str, str] = {}

    def iter_bytes(self, chunk_size: int) -> list[bytes]:
        return self._chunks

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeStreamingClient:
    def __init__(self, file_bytes: bytes) -> None:
        self._file_bytes = file_bytes

    def stream(
        self, method: str, url: str, headers: dict[str, str] | None = None
    ) -> _FakeStreamResponse:
        return _FakeStreamResponse(200, [self._file_bytes])


def _load(name: str) -> dict[str, Any]:
    with (GOLDEN_DIR / name).open() as f:
        result: dict[str, Any] = json.load(f)
        return result


def test_fetch_and_parse_bulk_partition_downloads_and_streams(tmp_path: Path) -> None:
    otc = _load("drug_label_otc.json")
    boxed = _load("drug_label_boxed_warning.json")

    # Build a real in-memory `*.json.zip` matching openFDA's actual bulk shape.
    inner_json = tmp_path / "drug-label-0001-of-0001.json"
    inner_json.write_text(json.dumps({"results": [otc, boxed]}))
    zip_path = tmp_path / "source.json.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(inner_json, arcname="drug-label-0001-of-0001.json")

    client = _FakeStreamingClient(zip_path.read_bytes())
    partition = BulkPartition(
        file_url="https://download.open.fda.gov/drug/label/drug-label-0001-of-0014.json.zip",
        display_name="/drug/label (part 1 of 14)",
        size_mb=1.0,
        records=2,
    )

    records = list(fetch_and_parse_bulk_partition(client, partition, tmp_path / "downloads"))  # type: ignore[arg-type]

    assert len(records) == 2
    assert all(isinstance(r, OpenFdaDrugLabelRecord) for r in records)
    assert records[0].set_id == "0000025c-6dbf-4af7-a741-5cbacaed519a"
    assert records[1].brand_name == "Naproxen"
    assert (tmp_path / "downloads" / "drug-label-0001-of-0014.json.zip").exists()
