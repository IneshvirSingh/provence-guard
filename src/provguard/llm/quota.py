"""Quota guard: per-model RPM/RPD/TPM/TPD fixed windows in Redis (or memory for tests).

It waits for the next window or raises :class:`QuotaExhausted`; it never lets a request exceed a limit.
Thread-safe when backed by Redis (atomic INCRBY); the benchmark runs AgentDojo's sync pipelines in threads.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from provguard.llm.providers import Limits

MINUTE = 60
DAY = 86_400


class QuotaExhausted(RuntimeError):
    """A window is full and waiting would exceed ``max_wait``; resume in the next window (daily cap)."""


class CounterStore(Protocol):
    def incr(self, key: str, amount: int, ttl: int) -> int:
        """Atomically add ``amount`` to ``key`` (created with ``ttl`` seconds) and return the new value."""

    def get(self, key: str) -> int: ...


class MemoryStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._data: dict[str, tuple[int, float]] = {}
        self._clock = clock

    def _live(self, key: str) -> int:
        value, expires = self._data.get(key, (0, 0.0))
        return value if expires > self._clock() else 0

    def incr(self, key: str, amount: int, ttl: int) -> int:
        current = self._live(key)
        if current == 0:
            self._data[key] = (amount, self._clock() + ttl)
            return amount
        self._data[key] = (current + amount, self._data[key][1])
        return current + amount

    def get(self, key: str) -> int:
        return self._live(key)


class RedisStore:
    """Thin adapter over redis-py (sync). ``client`` is any object with ``incrby``, ``expire``, ``get``."""

    def __init__(self, client: object) -> None:
        self._r = client

    def incr(self, key: str, amount: int, ttl: int) -> int:
        r = self._r
        value = int(r.incrby(key, amount))  # type: ignore[attr-defined]
        if value == amount:
            r.expire(key, ttl)  # type: ignore[attr-defined]
        return value

    def get(self, key: str) -> int:
        raw = self._r.get(key)  # type: ignore[attr-defined]
        return int(raw) if raw is not None else 0


@dataclass
class QuotaGuard:
    model_id: str
    limits: Limits
    store: CounterStore
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    max_wait: float = 90.0
    requests: int = field(default=0, init=False)
    tokens: int = field(default=0, init=False)
    waited: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if not self.limits.complete():
            raise ValueError(
                f"limits for {self.model_id} are incomplete ({self.limits.model_dump()}); "
                "copy them from the provider console into config/providers.yaml (HUMAN_TODO.md)"
            )

    # window helpers -------------------------------------------------------------------------------

    def _window(self, seconds: int) -> tuple[int, float]:
        now = self.clock()
        start = int(now // seconds) * seconds
        return start, start + seconds - now

    def _key(self, kind: str, seconds: int, start: int) -> str:
        return f"quota:{self.model_id}:{kind}:{seconds}:{start}"

    def _checks(self, tokens: int) -> list[tuple[str, int, int, int]]:
        """(kind, window seconds, amount, limit) for every configured window."""
        lim = self.limits
        assert lim.rpm is not None and lim.rpd is not None and lim.tpm is not None and lim.tpd is not None
        return [
            ("req", MINUTE, 1, lim.rpm),
            ("req", DAY, 1, lim.rpd),
            ("tok", MINUTE, tokens, lim.tpm),
            ("tok", DAY, tokens, lim.tpd),
        ]

    # public API ----------------------------------------------------------------------------------

    def acquire(self, estimated_tokens: int) -> None:
        """Reserve one request and ``estimated_tokens`` tokens, waiting for the next window if needed."""
        while True:
            blocking: float | None = None
            for kind, seconds, amount, limit in self._checks(estimated_tokens):
                start, remaining = self._window(seconds)
                if self.store.get(self._key(kind, seconds, start)) + amount > limit:
                    blocking = max(blocking or 0.0, remaining)
            if blocking is None:
                for kind, seconds, amount, _ in self._checks(estimated_tokens):
                    start, _ = self._window(seconds)
                    self.store.incr(self._key(kind, seconds, start), amount, seconds + 1)
                self.requests += 1
                self.tokens += estimated_tokens
                return
            if blocking > self.max_wait:
                raise QuotaExhausted(f"{self.model_id}: window full for {blocking:.0f}s; resume later")
            self.waited += blocking
            self.sleep(blocking + 0.05)

    def settle(self, estimated_tokens: int, actual_tokens: int) -> None:
        """True up token counters once the real usage is known (only ever adds; never refunds)."""
        extra = actual_tokens - estimated_tokens
        if extra > 0:
            for kind, seconds, _, _ in self._checks(0):
                if kind == "tok":
                    start, _ = self._window(seconds)
                    self.store.incr(self._key(kind, seconds, start), extra, seconds + 1)
            self.tokens += extra
