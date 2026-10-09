from __future__ import annotations

import pytest

from app.resilience import (
    BreakerState,
    CircuitBreaker,
    CircuitOpen,
    Deadline,
    DeadlineExceeded,
    TransientFailure,
    run_with_retries,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.anyio
async def test_retry_transient_failure_within_deadline():
    clock = FakeClock()
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TransientFailure("temporary")
        return "ok"

    result, retries = await run_with_retries(
        operation,
        Deadline(5, clock),
        retry_if=lambda error: isinstance(error, TransientFailure),
        sleep=clock.sleep,
        jitter=lambda _: 0,
    )
    assert (result, retries, attempts) == ("ok", 2, 3)


@pytest.mark.anyio
async def test_retry_does_not_repeat_permanent_failure():
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        await run_with_retries(
            operation, Deadline(5), retry_if=lambda error: isinstance(error, TransientFailure)
        )
    assert attempts == 1


def test_deadline_expires_from_injected_clock():
    clock = FakeClock()
    deadline = Deadline(3, clock)
    clock.now += 3
    with pytest.raises(DeadlineExceeded):
        deadline.remaining()


def test_circuit_breaker_opens_half_opens_and_recovers():
    clock = FakeClock()
    breaker = CircuitBreaker(clock=clock, failure_threshold=3, reset_seconds=15)
    for _ in range(3):
        breaker.failure()
    assert breaker.state == BreakerState.OPEN
    with pytest.raises(CircuitOpen):
        breaker.allow()
    clock.now += 15
    breaker.allow()
    assert breaker.state == BreakerState.HALF_OPEN
    with pytest.raises(CircuitOpen):
        breaker.allow()
    breaker.success()
    assert breaker.state == BreakerState.CLOSED
    assert breaker.failures == 0


def test_half_open_failure_reopens_circuit():
    clock = FakeClock()
    breaker = CircuitBreaker(clock=clock)
    for _ in range(3):
        breaker.failure()
    clock.now += 15
    breaker.allow()
    breaker.failure()
    assert breaker.state == BreakerState.OPEN
