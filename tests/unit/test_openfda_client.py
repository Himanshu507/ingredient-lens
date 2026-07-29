from typing import Any

import httpx
import pytest

from ingestion.openfda.client import (
    OpenFdaRateLimited,
    OpenFdaRequestError,
    OpenFdaServerError,
    _raise_for_status,
    fetch_page,
    iter_pages,
)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise retry *logic*, not backoff timing — no real sleep()."""
    monkeypatch.setattr("ingestion.common.retry.time.sleep", lambda seconds: None)


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}
        self.text = str(json_data)

    def json(self) -> dict[str, Any]:
        return self._json_data


class _FakeClient:
    """Stands in for httpx.Client: a queue of canned responses per `.get()` call."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, Any]) -> _FakeResponse:
        self.calls.append({"url": url, "params": params})
        return self._responses.pop(0)


def _page_response(records: list[dict[str, Any]]) -> _FakeResponse:
    return _FakeResponse(200, {"results": records})


def test_fetch_page_returns_json_on_success() -> None:
    client = _FakeClient([_page_response([{"set_id": "abc"}])])

    page = fetch_page(client, endpoint="drug/label", skip=0, limit=10)  # type: ignore[arg-type]

    assert page == {"results": [{"set_id": "abc"}]}
    assert client.calls[0]["params"] == {"skip": 0, "limit": 10}


def test_fetch_page_raises_rate_limited_and_does_not_retry_forever() -> None:
    client = _FakeClient([_FakeResponse(429, headers={"Retry-After": "1"})] * 10)

    with pytest.raises(Exception, match="exhausted"):
        fetch_page(client, endpoint="drug/label", skip=0, limit=10)  # type: ignore[arg-type]


def test_fetch_page_retries_server_error_then_succeeds() -> None:
    client = _FakeClient(
        [
            _FakeResponse(500),
            _FakeResponse(503),
            _page_response([{"set_id": "abc"}]),
        ]
    )

    page = fetch_page(client, endpoint="drug/label", skip=0, limit=10)  # type: ignore[arg-type]

    assert page == {"results": [{"set_id": "abc"}]}
    assert len(client.calls) == 3


def test_fetch_page_does_not_retry_client_error() -> None:
    client = _FakeClient([_FakeResponse(400)] * 5)

    with pytest.raises(OpenFdaRequestError):
        fetch_page(client, endpoint="drug/label", skip=0, limit=10)  # type: ignore[arg-type]

    assert len(client.calls) == 1


def test_raise_for_status_classification() -> None:
    with pytest.raises(OpenFdaRateLimited):
        _raise_for_status(httpx.Response(429, request=httpx.Request("GET", "http://x")))

    with pytest.raises(OpenFdaServerError):
        _raise_for_status(httpx.Response(500, request=httpx.Request("GET", "http://x")))

    with pytest.raises(OpenFdaRequestError):
        _raise_for_status(httpx.Response(404, request=httpx.Request("GET", "http://x")))


def test_iter_pages_stops_on_short_page() -> None:
    client = _FakeClient(
        [
            _page_response([{"set_id": "1"}, {"set_id": "2"}]),
            _page_response([{"set_id": "3"}]),
        ]
    )

    pages = list(iter_pages(client, endpoint="drug/label", page_size=2))  # type: ignore[arg-type]

    assert pages == [[{"set_id": "1"}, {"set_id": "2"}], [{"set_id": "3"}]]
    assert client.calls[0]["params"]["skip"] == 0
    assert client.calls[1]["params"]["skip"] == 2


def test_iter_pages_stops_on_empty_page() -> None:
    client = _FakeClient([_page_response([])])

    pages = list(iter_pages(client, endpoint="drug/label", page_size=2))  # type: ignore[arg-type]

    assert pages == []
