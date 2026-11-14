import json
from pathlib import Path

import pytest

from provguard.llm.filestore import FileCache, FileCounterStore
from provguard.llm.providers import Limits
from provguard.llm.quota import QuotaExhausted, QuotaGuard


def test_file_cache_survives_reopen_and_torn_last_line(tmp_path: Path) -> None:
    path = tmp_path / "state" / "cache.jsonl"
    cache = FileCache(path)
    assert cache.get("a") is None
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("a", "3")
    with path.open("a") as fh:
        fh.write('{"k": "c", "v": "tor')  # job killed mid-write
    reopened = FileCache(path)
    assert (reopened.get("a"), reopened.get("b"), reopened.get("c")) == ("3", "2", None)
    assert len(reopened) == 2


def test_file_counters_persist_expire_and_prune(tmp_path: Path) -> None:
    now = [1000.0]
    path = tmp_path / "quota.json"
    store = FileCounterStore(path, clock=lambda: now[0])
    assert store.incr("day", 5, ttl=100) == 5
    assert store.incr("day", 2, ttl=100) == 7
    assert store.incr("minute", 1, ttl=10) == 1
    assert FileCounterStore(path, clock=lambda: now[0]).get("day") == 7
    now[0] += 50
    assert store.get("minute") == 0
    assert store.incr("day", 1, ttl=100) == 8  # keeps the original expiry
    assert "minute" not in json.loads(path.read_text())
    now[0] += 51
    assert store.get("day") == 0
    assert store.incr("day", 4, ttl=100) == 4


def test_file_counters_refuse_corrupt_state(tmp_path: Path) -> None:
    path = tmp_path / "quota.json"
    path.write_text("{not json")
    with pytest.raises(ValueError, match="unreadable"):
        FileCounterStore(path)


def test_daily_budget_is_shared_between_jobs(tmp_path: Path) -> None:
    """Two jobs on the same UTC day share one budget through the persisted counter file."""
    limits = Limits(rpm=100, rpd=100, tpm=1000, tpd=150)
    clock = lambda: 86_400.0 * 10 + 5  # noqa: E731

    def job() -> QuotaGuard:
        return QuotaGuard("m", limits, FileCounterStore(tmp_path / "quota.json", clock=clock), clock=clock)

    job().acquire(100)
    with pytest.raises(QuotaExhausted):
        job().acquire(100)
