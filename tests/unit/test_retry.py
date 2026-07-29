from collections.abc import Callable

import pytest

from ingestion.common.retry import RetryExhausted, call_with_retry


class _Retryable(Exception):
    pass


class _NotRetryable(Exception):
    pass


def _fake_clock() -> tuple[list[float], Callable[[float], None]]:
    """Returns (recorded_delays, sleep_fn) — no real wall-clock time used."""
    recorded: list[float] = []

    def sleep(seconds: float) -> None:
        recorded.append(seconds)

    return recorded, sleep


def test_succeeds_immediately_without_retrying() -> None:
    calls = 0

    def fn() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    result = call_with_retry(fn, is_retryable=lambda exc: True)

    assert result == "ok"
    assert calls == 1


def test_retries_transient_failure_then_succeeds() -> None:
    recorded_delays, sleep = _fake_clock()
    attempts = {"count": 0}

    def fn() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _Retryable("transient")
        return "ok"

    result = call_with_retry(
        fn,
        is_retryable=lambda exc: isinstance(exc, _Retryable),
        base_delay_seconds=1.0,
        jitter=lambda: 0.0,
        sleep=sleep,
    )

    assert result == "ok"
    assert attempts["count"] == 3
    # exponential: 1.0, 2.0 (no jitter, since jitter() == 0.0)
    assert recorded_delays == [1.0, 2.0]


def test_non_retryable_exception_propagates_immediately() -> None:
    calls = 0

    def fn() -> str:
        nonlocal calls
        calls += 1
        raise _NotRetryable("bad request")

    with pytest.raises(_NotRetryable):
        call_with_retry(fn, is_retryable=lambda exc: isinstance(exc, _Retryable))

    assert calls == 1


def test_exhausts_max_attempts_and_raises_retry_exhausted() -> None:
    recorded_delays, sleep = _fake_clock()
    calls = 0

    def fn() -> str:
        nonlocal calls
        calls += 1
        raise _Retryable("always fails")

    with pytest.raises(RetryExhausted) as exc_info:
        call_with_retry(
            fn,
            is_retryable=lambda exc: isinstance(exc, _Retryable),
            max_attempts=3,
            jitter=lambda: 0.0,
            sleep=sleep,
        )

    assert calls == 3
    assert exc_info.value.attempts == 3
    assert len(recorded_delays) == 2  # slept between attempts 1->2 and 2->3, not after the last


def test_retry_after_override_takes_precedence_over_backoff() -> None:
    recorded_delays, sleep = _fake_clock()
    attempts = {"count": 0}

    class _RateLimited(Exception):
        def __init__(self) -> None:
            super().__init__("429")
            self.retry_after = 42.0

    def fn() -> str:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise _RateLimited
        return "ok"

    result = call_with_retry(
        fn,
        is_retryable=lambda exc: isinstance(exc, _RateLimited),
        retry_after=lambda exc: exc.retry_after if isinstance(exc, _RateLimited) else None,
        sleep=sleep,
    )

    assert result == "ok"
    assert recorded_delays == [42.0]
