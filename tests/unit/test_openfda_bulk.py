import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

from ingestion.openfda.bulk import (
    DownloadError,
    download_partition,
    download_partition_with_retry,
    iter_records_from_bulk_zip,
)
from ingestion.openfda.bulk_manifest import BulkPartition


class _FakeStreamResponse:
    def __init__(
        self, status_code: int, chunks: list[bytes], headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.headers = headers or {}
        self.closed = False

    def iter_bytes(self, chunk_size: int) -> list[bytes]:
        return self._chunks

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeStreamingClient:
    """Stands in for httpx.Client's `.stream()` — a queue of canned responses/errors."""

    def __init__(self, responses: list[_FakeStreamResponse | Exception]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def stream(
        self, method: str, url: str, headers: dict[str, str] | None = None
    ) -> _FakeStreamResponse:
        self.requests.append({"method": method, "url": url, "headers": headers or {}})
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


_PARTITION = BulkPartition(
    file_url="https://download.open.fda.gov/drug/label/drug-label-0001-of-0014.json.zip",
    display_name="/drug/label (part 1 of 14)",
    size_mb=1.0,
    records=2,
)


def test_download_partition_writes_chunks_to_disk(tmp_path: Path) -> None:
    client = _FakeStreamingClient([_FakeStreamResponse(200, [b"hello ", b"world"])])
    dest = tmp_path / "part.zip"

    result = download_partition(client, _PARTITION, dest)  # type: ignore[arg-type]

    assert result == dest
    assert dest.read_bytes() == b"hello world"
    assert client.requests[0]["headers"] == {}


def test_download_partition_resumes_with_range_header(tmp_path: Path) -> None:
    dest = tmp_path / "part.zip"
    dest.write_bytes(b"hello ")
    client = _FakeStreamingClient([_FakeStreamResponse(206, [b"world"])])

    result = download_partition(client, _PARTITION, dest)  # type: ignore[arg-type]

    assert result == dest
    assert dest.read_bytes() == b"hello world"
    assert client.requests[0]["headers"] == {"Range": "bytes=6-"}


def test_download_partition_restarts_when_server_ignores_range(tmp_path: Path) -> None:
    dest = tmp_path / "part.zip"
    dest.write_bytes(b"stale-partial-data")
    client = _FakeStreamingClient(
        [
            _FakeStreamResponse(200, [b"full content"]),  # range ignored -> restart
            _FakeStreamResponse(200, [b"full content"]),  # retried from scratch
        ]
    )

    result = download_partition(client, _PARTITION, dest)  # type: ignore[arg-type]

    assert result == dest
    assert dest.read_bytes() == b"full content"
    assert client.requests[0]["headers"] == {"Range": "bytes=18-"}
    assert client.requests[1]["headers"] == {}


def test_download_partition_treats_416_as_already_complete(tmp_path: Path) -> None:
    dest = tmp_path / "part.zip"
    dest.write_bytes(b"already fully downloaded")
    client = _FakeStreamingClient([_FakeStreamResponse(416, [])])

    result = download_partition(client, _PARTITION, dest)  # type: ignore[arg-type]

    assert result == dest
    assert dest.read_bytes() == b"already fully downloaded"


def test_download_partition_raises_on_unexpected_status(tmp_path: Path) -> None:
    client = _FakeStreamingClient([_FakeStreamResponse(500, [])])
    dest = tmp_path / "part.zip"

    with pytest.raises(DownloadError):
        download_partition(client, _PARTITION, dest)  # type: ignore[arg-type]


def test_download_partition_with_retry_retries_transport_error(tmp_path: Path) -> None:
    client = _FakeStreamingClient(
        [
            httpx.ConnectError("connection reset"),
            _FakeStreamResponse(200, [b"data"]),
        ]
    )
    dest = tmp_path / "part.zip"

    result = download_partition_with_retry(
        client,  # type: ignore[arg-type]
        _PARTITION,
        dest,
        sleep=lambda seconds: None,
        jitter=lambda: 0.0,
    )

    assert result == dest
    assert dest.read_bytes() == b"data"


def test_iter_records_from_bulk_zip_streams_records(tmp_path: Path) -> None:
    payload = {
        "meta": {"results": {"skip": 0, "limit": 2, "total": 2}},
        "results": [{"set_id": "a", "name": "First"}, {"set_id": "b", "name": "Second"}],
    }
    json_path = tmp_path / "drug-label-0001-of-0001.json"
    json_path.write_text(json.dumps(payload))
    zip_path = tmp_path / "drug-label-0001-of-0001.json.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(json_path, arcname=json_path.name)

    records = list(iter_records_from_bulk_zip(zip_path))

    assert records == [{"set_id": "a", "name": "First"}, {"set_id": "b", "name": "Second"}]


def test_iter_records_from_bulk_zip_rejects_multi_member_archive(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("one.json", "{}")
        archive.writestr("two.json", "{}")

    with pytest.raises(DownloadError):
        list(iter_records_from_bulk_zip(zip_path))
