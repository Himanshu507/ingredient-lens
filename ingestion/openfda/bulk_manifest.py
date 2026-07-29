from dataclasses import dataclass
from typing import Any

import httpx

DOWNLOAD_MANIFEST_URL = "https://api.fda.gov/download.json"


@dataclass(frozen=True)
class BulkPartition:
    """One downloadable file within an endpoint's full bulk export."""

    file_url: str
    display_name: str
    size_mb: float
    records: int


def fetch_download_manifest(client: httpx.Client) -> dict[str, Any]:
    """Fetch openFDA's bulk-download manifest (small — a list of files, not data)."""
    response = client.get(DOWNLOAD_MANIFEST_URL)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def list_partitions(
    manifest: dict[str, Any], *, category: str, endpoint: str
) -> list[BulkPartition]:
    """Extract the partition list for one endpoint, e.g. category="drug", endpoint="label"."""
    endpoint_data = manifest["results"][category][endpoint]
    return [
        BulkPartition(
            file_url=partition["file"],
            display_name=partition["display_name"],
            size_mb=float(partition["size_mb"]),
            records=int(partition["records"]),
        )
        for partition in endpoint_data["partitions"]
    ]
