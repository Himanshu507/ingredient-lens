import json
from pathlib import Path
from typing import Any

from ingestion.openfda.bulk_manifest import BulkPartition, list_partitions

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "openfda"


def _load_manifest() -> dict[str, Any]:
    with (GOLDEN_DIR / "download_manifest_trimmed.json").open() as f:
        result: dict[str, Any] = json.load(f)
        return result


def test_list_partitions_extracts_drug_label_partitions() -> None:
    """Real (trimmed) manifest from api.fda.gov/download.json."""
    manifest = _load_manifest()

    partitions = list_partitions(manifest, category="drug", endpoint="label")

    assert len(partitions) == 2
    assert partitions[0] == BulkPartition(
        file_url="https://download.open.fda.gov/drug/label/drug-label-0001-of-0014.json.zip",
        display_name="/drug/label (part 1 of 14)",
        size_mb=130.30,
        records=20000,
    )
    assert partitions[1].file_url.endswith("drug-label-0002-of-0014.json.zip")
