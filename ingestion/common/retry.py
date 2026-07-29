import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RetryExhausted(Exception):
    """Raised when a retryable call fails on every attempt up to `max_attempts`.

    Per INGESTION_STRATEGY.md Section 3: infinite retry is indistinguishable
    from a hang, so callers surface this to the error-handling/alerting path
    rather than looping forever.
    """

    def __init__(self, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"exhausted {attempts} attempt(s), last error: {last_error!r}")
        self.attempts = attempts
        self.last_error = last_error


def call_with_retry(
    fn: Callable[[], T],
    *,
    is_retryable: Callable[[BaseException], bool],
    max_attempts: int = 5,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 60.0,
    retry_after: Callable[[BaseException], float | None] | None = None,
    sleep: Callable[[float], None] | None = None,
    jitter: Callable[[], float] | None = None,
) -> T:
    """Call `fn`, retrying on retryable failures with exponential backoff + jitter.

    - Non-retryable exceptions (per `is_retryable`) propagate immediately —
      e.g. a 4xx other than 429 indicates a bad request, not a transient issue.
    - `retry_after`, if given, lets a specific error (e.g. HTTP 429) override the
      computed delay with a source-provided value (e.g. a `Retry-After` header).
    - `sleep`/`jitter` are injectable so tests exercise real backoff math without
      real wall-clock time or non-deterministic randomness (TESTING_STRATEGY.md §7).
      Resolved here rather than as literal default parameter values, so patching
      `time.sleep` at the module level (as callers not exposing their own `sleep`
      parameter must) actually takes effect — a default bound at function-definition
      time would ignore any later monkeypatching.
    """
    sleep = sleep if sleep is not None else time.sleep
    jitter = jitter if jitter is not None else random.random

    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc):
                raise
            if attempt >= max_attempts:
                raise RetryExhausted(attempt, exc) from exc

            override = retry_after(exc) if retry_after else None
            if override is not None:
                delay = override
            else:
                delay = min(base_delay_seconds * (2 ** (attempt - 1)), max_delay_seconds)
                delay += jitter() * delay

            sleep(delay)
