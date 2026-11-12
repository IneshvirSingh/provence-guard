import fakeredis
import pytest

from provguard.llm.providers import Limits
from provguard.llm.quota import MemoryStore, QuotaExhausted, QuotaGuard, RedisStore


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s


def make(
    limits: Limits, store=None, clock: Clock | None = None, max_wait: float = 90.0
) -> tuple[QuotaGuard, Clock]:
    clock = clock or Clock()
    store = store or MemoryStore(clock)
    return QuotaGuard("groq/test", limits, store, clock=clock, sleep=clock.sleep, max_wait=max_wait), clock


def test_incomplete_limits_refused():
    with pytest.raises(ValueError, match="incomplete"):
        make(Limits(rpm=1, rpd=None, tpm=1, tpd=1))


def test_rpm_waits_for_next_minute_window():
    guard, clock = make(Limits(rpm=2, rpd=100, tpm=10_000, tpd=1_000_000))
    guard.acquire(10)
    guard.acquire(10)
    guard.acquire(10)  # third request must wait for the next minute
    assert len(clock.slept) == 1 and 0 < clock.slept[0] <= 60.1
    assert guard.requests == 3 and guard.tokens == 30 and guard.waited > 0


def test_tpm_counts_tokens_and_settle_only_adds():
    guard, clock = make(Limits(rpm=100, rpd=100, tpm=100, tpd=1_000_000))
    guard.acquire(60)
    guard.settle(60, 90)  # real usage was higher: 30 extra tokens recorded
    assert guard.tokens == 90
    guard.settle(60, 10)  # lower: never refunded
    assert guard.tokens == 90
    guard.acquire(5)  # 95 <= 100 ok
    guard.acquire(10)  # would be 105 -> wait
    assert clock.slept


def test_daily_cap_raises_instead_of_waiting_hours():
    guard, _ = make(Limits(rpm=100, rpd=1, tpm=10_000, tpd=1_000_000))
    guard.acquire(1)
    with pytest.raises(QuotaExhausted):
        guard.acquire(1)


def test_redis_store_with_fakeredis():
    r = fakeredis.FakeRedis()
    store = RedisStore(r)
    assert store.get("k") == 0
    assert store.incr("k", 2, 60) == 2 and store.incr("k", 3, 60) == 5 and store.get("k") == 5
    assert 0 < r.ttl("k") <= 60
    guard, _ = make(Limits(rpm=1, rpd=10, tpm=10_000, tpd=1_000_000), store=store)
    guard.acquire(1)
    assert len([k for k in r.keys() if k.startswith(b"quota:groq/test")]) == 4  # noqa: SIM118 - redis API


def test_memory_store_expires():
    clock = Clock()
    store = MemoryStore(clock)
    store.incr("k", 1, 10)
    clock.now += 11
    assert store.get("k") == 0 and store.incr("k", 1, 10) == 1
