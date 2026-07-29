from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ingestion.openfda.bulk import download_partition_with_retry, iter_records_from_bulk_zip
from ingestion.openfda.bulk_manifest import BulkPartition
from ingestion.openfda.models import OpenFdaDrugLabelRecord
from ingestion.openfda.parser import parse_drug_label_record


def fetch_and_parse_bulk_partition(
    client: httpx.Client,
    partition: BulkPartition,
    dest_dir: Path,
) -> Iterator[OpenFdaDrugLabelRecord]:
    """Download one bulk partition (resumable) and stream-parse it.

    This is the bootstrap path for the initial multi-million-record backfill
    (OPENFDA_INGESTION.md Section 2) — as opposed to `adapter.fetch_and_parse_drug_labels`,
    which paginates the live API for incremental syncs. No canonical model, no
    database writes here; that's Brick 6.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / Path(urlparse(partition.file_url).path).name

    download_partition_with_retry(client, partition, dest_path)

    for raw_record in iter_records_from_bulk_zip(dest_path):
        yield parse_drug_label_record(raw_record)
