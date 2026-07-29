from collections.abc import Iterator
from typing import Any

import httpx

from ingestion.common.retry import call_with_retry

OPENFDA_BASE_URL = "https://api.fda.gov"

# openFDA's documented maximum page size for most endpoints, including drug/label.
DEFAULT_PAGE_SIZE = 100


class OpenFdaRateLimited(Exception):
    """HTTP 429 — retryable, and paced by `Retry-After` when openFDA sends one."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__("openFDA rate limit (429)")
        self.retry_after = retry_after


class OpenFdaServerError(Exception):
    """HTTP 5xx — transient, retryable."""


class OpenFdaRequestError(Exception):
    """HTTP 4xx other than 429 — a bad query on our side, not retried.

    Per OPENFDA_INGESTION.md Section 5: retrying a malformed request just
    wastes time and can look like a stuck process.
    """


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 429:
        retry_after_header = response.headers.get("Retry-After")
        retry_after = float(retry_after_header) if retry_after_header else None
        raise OpenFdaRateLimited(retry_after)
    if response.status_code >= 500:
        raise OpenFdaServerError(f"openFDA returned {response.status_code}")
    if response.status_code >= 400:
        raise OpenFdaRequestError(f"openFDA returned {response.status_code}: {response.text}")


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, OpenFdaRateLimited | OpenFdaServerError | httpx.TransportError)


def _retry_after(exc: BaseException) -> float | None:
    return exc.retry_after if isinstance(exc, OpenFdaRateLimited) else None


def fetch_page(
    client: httpx.Client,
    *,
    endpoint: str,
    skip: int,
    limit: int = DEFAULT_PAGE_SIZE,
    api_key: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """Fetch one page of raw JSON from an openFDA endpoint, with retry/backoff."""
    params: dict[str, Any] = {"skip": skip, "limit": limit}
    if api_key:
        params["api_key"] = api_key
    if search:
        params["search"] = search

    def _do_request() -> dict[str, Any]:
        response = client.get(f"{OPENFDA_BASE_URL}/{endpoint}.json", params=params)
        _raise_for_status(response)
        result: dict[str, Any] = response.json()
        return result

    return call_with_retry(_do_request, is_retryable=_is_retryable, retry_after=_retry_after)


def iter_pages(
    client: httpx.Client,
    *,
    endpoint: str,
    api_key: str | None = None,
    search: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    start_skip: int = 0,
) -> Iterator[list[dict[str, Any]]]:
    """Yield successive pages of raw records, one page at a time (no accumulation).

    Terminates on a short page (fewer records than `page_size`), per
    OPENFDA_INGESTION.md Section 3 — not on openFDA's reported total, which can
    drift during a long-running sync.
    """
    skip = start_skip
    while True:
        page = fetch_page(
            client, endpoint=endpoint, skip=skip, limit=page_size, api_key=api_key, search=search
        )
        results: list[dict[str, Any]] = page.get("results", [])
        if not results:
            return
        yield results
        if len(results) < page_size:
            return
        skip += page_size
