"""Per-patient rate limiting for the action gateway (loop L19 / L31 / L32).

A sliding-window counter keyed on patient id. Storage is injectable via
`RateLimitStore` so a Postgres-backed counter table (listed among the new
Postgres uses in architecture.md section 2: "rate-limit counters") can
replace the in-memory default without changing `RateLimiter` or the
gateway.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)


class RateLimitStore(Protocol):
    """Storage seam for sliding-window timestamps per patient."""

    def get_timestamps(self, patient_id: str) -> list[float]: ...

    def set_timestamps(self, patient_id: str, timestamps: list[float]) -> None: ...


class InMemoryRateLimitStore:
    def __init__(self) -> None:
        self._timestamps: dict[str, list[float]] = {}

    def get_timestamps(self, patient_id: str) -> list[float]:
        return list(self._timestamps.get(patient_id, []))

    def set_timestamps(self, patient_id: str, timestamps: list[float]) -> None:
        self._timestamps[patient_id] = timestamps


class RateLimiter:
    """Sliding-window limiter: at most `max_actions` per `window_seconds`,
    per patient."""

    def __init__(
        self,
        max_actions: int = 5,
        window_seconds: float = 60.0,
        store: RateLimitStore | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._max_actions = max_actions
        self._window_seconds = window_seconds
        self._store = store or InMemoryRateLimitStore()
        self._clock = clock

    def allow(self, patient_id: str) -> bool:
        """Checks and, if allowed, records this call as a consumed slot.

        Returns True (and records the timestamp) if under the limit, False
        (no recording) if the patient is currently rate-limited.
        """
        now = self._clock()
        window_start = now - self._window_seconds
        timestamps = [t for t in self._store.get_timestamps(patient_id) if t >= window_start]

        if len(timestamps) >= self._max_actions:
            self._store.set_timestamps(patient_id, timestamps)
            logger.warning(
                "rate_limiter.exceeded",
                patient_id=patient_id,
                count=len(timestamps),
                max_actions=self._max_actions,
                window_seconds=self._window_seconds,
            )
            return False

        timestamps.append(now)
        self._store.set_timestamps(patient_id, timestamps)
        logger.info(
            "rate_limiter.allowed",
            patient_id=patient_id,
            count=len(timestamps),
            max_actions=self._max_actions,
        )
        return True
