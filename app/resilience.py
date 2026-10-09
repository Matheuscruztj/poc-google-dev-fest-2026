"""Deadlines, bounded retries, and per-process dependency circuit breakers."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

T = TypeVar("T")


class DeadlineExceeded(TimeoutError):
    pass


class TransientFailure(RuntimeError):
    """A read-only operation may be retried within its shared deadline."""


@dataclass
class Deadline:
    seconds: float
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self.expires_at = self.clock() + self.seconds

    def remaining(self) -> float:
        remaining = self.expires_at - self.clock()
        if remaining <= 0:
            raise DeadlineExceeded("O prazo global da solicitação foi excedido.")
        return remaining


async def run_with_retries(
    operation: Callable[[], Awaitable[T]],
    deadline: Deadline,
    *,
    retry_if: Callable[[Exception], bool],
    max_retries: int = 2,
    base_delay: float = 0.05,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    jitter: Callable[[float], float] = lambda value: random.uniform(0, value),
) -> tuple[T, int]:
    retries = 0
    while True:
        try:
            return await asyncio.wait_for(operation(), timeout=deadline.remaining()), retries
        except Exception as exc:
            if retries >= max_retries or not retry_if(exc):
                raise
            delay = base_delay * (2**retries)
            wait_for = min(delay + jitter(delay), deadline.remaining())
            if wait_for <= 0:
                raise DeadlineExceeded("Sem prazo restante para nova tentativa.") from exc
            await sleep(wait_for)
            retries += 1


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpen(RuntimeError):
    pass


class CircuitBreaker:
    """One process-local breaker; state is not shared across replicas."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        reset_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.clock = clock
        self.state = BreakerState.CLOSED
        self.failures = 0
        self.opened_at: float | None = None
        self._probe_in_flight = False

    def allow(self) -> None:
        if self.state == BreakerState.OPEN:
            assert self.opened_at is not None
            if self.clock() - self.opened_at < self.reset_seconds:
                raise CircuitOpen("A dependência está temporariamente indisponível.")
            self.state = BreakerState.HALF_OPEN
        if self.state == BreakerState.HALF_OPEN:
            if self._probe_in_flight:
                raise CircuitOpen("A tentativa controlada já está em andamento.")
            self._probe_in_flight = True

    def success(self) -> None:
        self.state = BreakerState.CLOSED
        self.failures = 0
        self.opened_at = None
        self._probe_in_flight = False

    def failure(self) -> None:
        self._probe_in_flight = False
        self.failures += 1
        if self.state == BreakerState.HALF_OPEN or self.failures >= self.failure_threshold:
            self.state = BreakerState.OPEN
            self.opened_at = self.clock()
