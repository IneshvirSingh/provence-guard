"""File-backed cache and quota counters for runs without Redis (GitHub Actions chunks, ADR-005).

Both live in one state directory that is persisted between jobs. The cache is an append-only JSON-lines file,
so a job killed mid-run loses at most the line being written. Single-process use only: the counters are not
atomic across processes (Redis is, and stays the choice for the Codespace).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

CACHE_FILE = "llm-cache.jsonl"
QUOTA_FILE = "quota.json"


class FileCache:
    """``CacheStore`` over an append-only JSONL file of ``{"k": key, "v": value}`` records (last one wins)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    record = json.loads(line)
                    self._data[record["k"]] = record["v"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue  # a torn last line from a killed job; the request is simply made again

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as fh:
                fh.write(json.dumps({"k": key, "v": value}, separators=(",", ":")) + "\n")
                fh.flush()


class FileCounterStore:
    """``CounterStore`` persisted as one small JSON file ``{key: [value, expires_at]}``.

    Day-window counters survive between jobs, so two chunks dispatched on the same UTC day share one budget.
    Expired keys are dropped on every write, so the file stays a handful of entries.
    """

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._data: dict[str, tuple[int, float]] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                self._data = {str(k): (int(v[0]), float(v[1])) for k, v in raw.items()}
            except (json.JSONDecodeError, TypeError, ValueError, IndexError, AttributeError) as exc:
                # Refuse to guess: starting from zero could overspend the provider's daily quota.
                raise ValueError(f"quota state {path} is unreadable; fix or delete it deliberately") from exc

    def _live(self, key: str) -> int:
        value, expires = self._data.get(key, (0, 0.0))
        return value if expires > self._clock() else 0

    def get(self, key: str) -> int:
        return self._live(key)

    def incr(self, key: str, amount: int, ttl: int) -> int:
        with self._lock:
            now = self._clock()
            current = self._live(key)
            expires = self._data[key][1] if current else now + ttl
            self._data[key] = (current + amount, expires)
            self._data = {k: v for k, v in self._data.items() if v[1] > now}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, sort_keys=True))
            tmp.replace(self.path)
            return current + amount


__all__ = ["CACHE_FILE", "QUOTA_FILE", "FileCache", "FileCounterStore"]
