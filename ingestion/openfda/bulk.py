import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import ijson

from ingestion.common.retry import call_with_retry
from ingestion.openfda.bulk_manifest import BulkPartition

DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class DownloadError(Exception):
    """A bulk download failed with an unexpected, non-range-related HTTP status."""


def download_partition(
    client: httpx.Client,
    partition: BulkPartition,
    dest_path: Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Path:
    """Stream one bulk partition to disk in chunks — never held fully in memory.

    Resumes from `dest_path`'s current size via an HTTP Range request if a
    partial download already exists. If the server doesn't honor the range
    (responds 200 instead of 206), the partial file is discarded and the
    download restarts from zero — per OPENFDA_INGESTION.md Section 5.
    """
    resume_from = dest_path.stat().st_size if dest_path.exists() else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}

    with client.stream("GET", partition.file_url, headers=headers) as response:
        if resume_from and response.status_code == 200:
            response.close()
            dest_path.unlink()
            return download_partition(client, partition, dest_path, chunk_size=chunk_size)

        if response.status_code == 416:
            # Range not satisfiable -- nothing left to fetch, already complete.
            return dest_path

        if response.status_code not in (200, 206):
            raise DownloadError(
                f"unexpected status {response.status_code} downloading {partition.file_url}"
            )

        mode = "ab" if response.status_code == 206 else "wb"
        with dest_path.open(mode) as f:
            for chunk in response.iter_bytes(chunk_size):
                f.write(chunk)

    return dest_path


def _is_retryable_download_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, DownloadError)


def download_partition_with_retry(
    client: httpx.Client,
    partition: BulkPartition,
    dest_path: Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    sleep: Callable[[float], None] | None = None,
    jitter: Callable[[], float] | None = None,
) -> Path:
    """`download_partition`, retried on transient network/server failures.

    A failure mid-stream leaves the partial file on disk (chunks are written
    as they arrive), so each retry attempt resumes from where the last one
    left off rather than restarting the whole ~100MB+ partition.
    """

    def _attempt() -> Path:
        return download_partition(client, partition, dest_path, chunk_size=chunk_size)

    return call_with_retry(
        _attempt,
        is_retryable=_is_retryable_download_error,
        sleep=sleep,
        jitter=jitter,
    )


def iter_records_from_bulk_zip(zip_path: Path) -> Iterator[dict[str, Any]]:
    """Stream individual records out of a downloaded `*.json.zip` bulk file.

    The ZIP's central directory lives at the end of the file, so reading it
    needs a seekable local file — this is why the file is downloaded to disk
    first rather than decompressed straight off the wire. The JSON *inside*
    the single member is still parsed incrementally via `ijson`, never
    `json.load()`-ed whole: peak memory is bounded by one record, not the
    ~130MB/20,000-record partition (OPENFDA_INGESTION.md Section 4).
    """
    with zipfile.ZipFile(zip_path) as archive:
        member_names = archive.namelist()
        if len(member_names) != 1:
            raise DownloadError(f"expected exactly one member in {zip_path}, found {member_names}")

        with archive.open(member_names[0]) as json_stream:
            yield from ijson.items(json_stream, "results.item")
