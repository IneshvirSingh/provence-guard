import json
from pathlib import Path

import pytest

from provguard.llm.client import CassetteMiss, LLMClient, MemoryCache, RedisCache, cache_key, estimate_tokens
from provguard.llm.providers import Limits, ModelRef
from provguard.llm.quota import MemoryStore, QuotaGuard

REF = ModelRef(
    provider="groq",
    model="m",
    base_url="https://x",
    api_key_env="X",
    limits=Limits(rpm=5, rpd=50, tpm=5000, tpd=50000),
)


def response(text: str = "hi", tool_call: dict | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": text}
    if tool_call:
        msg["tool_calls"] = [{"id": "c1", "type": "function", "function": tool_call}]
    return {
        "model": "m",
        "choices": [{"message": msg}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class Transport:
    def __init__(self, responses=None, fail_times: int = 0, exc: type[Exception] = ConnectionError) -> None:
        self.calls: list[dict] = []
        self.responses = list(responses or [])
        self.fail_times = fail_times
        self.exc = exc

    def __call__(self, payload: dict) -> dict:
        self.calls.append(payload)
        if self.fail_times:
            self.fail_times -= 1
            raise self.exc("boom")
        return self.responses.pop(0) if self.responses else response()


MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


def test_cache_hit_makes_zero_calls_and_counts():
    t = Transport()
    c = LLMClient(REF, transport=t)
    r1 = c.chat(MSGS, [{"type": "function", "function": {"name": "f"}}])
    r2 = c.chat(MSGS, [{"type": "function", "function": {"name": "f"}}])
    assert len(t.calls) == 1 and not r1.cached and r2.cached and r1.key == r2.key
    assert t.calls[0]["tool_choice"] == "auto" and t.calls[0]["seed"] == 0
    assert c.summary.requests == 1 and c.summary.cache_hits == 1 and c.summary.total_tokens == 15
    assert c.chat(MSGS, temperature=0.5).key != r1.key  # different params -> different key


def test_quota_guard_is_consulted_and_settled():
    clock = lambda: 1.0  # noqa: E731
    store = MemoryStore(clock)
    guard = QuotaGuard("groq/m", REF.limits, store, clock=clock, sleep=lambda s: None)
    c = LLMClient(REF, transport=Transport(), quota=guard)
    c.chat(MSGS)
    assert guard.requests == 1 and guard.tokens >= 15
    c.chat(MSGS)  # cached: no quota use
    assert guard.requests == 1


def test_replay_mode_raises_on_miss_and_record_writes_cassette(tmp_path: Path):
    tape = tmp_path / "tape.json"
    with pytest.raises(CassetteMiss):
        LLMClient(REF, transport=Transport(), mode="replay", cassette=tape).chat(MSGS)
    rec = LLMClient(REF, transport=Transport([response("recorded")]), mode="record", cassette=tape)
    assert rec.chat(MSGS).message["content"] == "recorded"
    assert json.loads(tape.read_text())
    rep = LLMClient(REF, transport=Transport(), mode="replay", cassette=tape)
    r = rep.chat(MSGS)
    assert r.cached and r.message["content"] == "recorded" and rep.summary.requests == 0


def test_retries_transient_then_succeeds_and_gives_up():
    sleeps: list[float] = []
    c = LLMClient(REF, transport=Transport(fail_times=2), sleep=sleeps.append, retry_predicate=lambda e: True)
    assert c.chat(MSGS).message["content"] == "hi" and c.summary.retries == 2 and len(sleeps) == 2
    c2 = LLMClient(
        REF,
        transport=Transport(fail_times=9),
        sleep=sleeps.append,
        max_retries=2,
        retry_predicate=lambda e: True,
    )
    with pytest.raises(ConnectionError):
        c2.chat(MSGS)
    c3 = LLMClient(
        REF, transport=Transport(fail_times=1), sleep=sleeps.append, retry_predicate=lambda e: False
    )
    with pytest.raises(ConnectionError):
        c3.chat(MSGS)


def test_bad_response_and_redis_cache(tmp_path):
    import fakeredis

    c = LLMClient(REF, transport=Transport([{"choices": []}]), cache=RedisCache(fakeredis.FakeRedis()))
    with pytest.raises(ValueError, match="no choices"):
        c.chat(MSGS)
    cache = RedisCache(fakeredis.FakeRedis())
    c = LLMClient(REF, transport=Transport(), cache=cache)
    c.chat(MSGS, max_tokens=5)
    assert cache.get(c.chat(MSGS, max_tokens=5).key) is not None


def test_helpers():
    assert cache_key("a", {"x": 1}) == cache_key("a", {"x": 1}) != cache_key("b", {"x": 1})
    assert estimate_tokens({"messages": MSGS}) > 64
    m = MemoryCache()
    m.set("k", "v")
    assert m.get("k") == "v" and m.get("z") is None


def test_record_mode_writes_cache_hits_into_the_cassette(tmp_path):
    from provguard.llm.client import LLMClient, MemoryCache
    from provguard.llm.providers import Limits, ModelRef

    ref = ModelRef(provider="p", model="m", base_url="https://x", api_key_env="X", limits=Limits())
    cache = MemoryCache()
    calls = 0

    def transport(payload):
        nonlocal calls
        calls += 1
        return {
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "usage": {"total_tokens": 3},
        }

    live = LLMClient(ref, transport=transport, cache=cache)
    live.chat([{"role": "user", "content": "x"}])  # warms the shared cache, no cassette
    tape = tmp_path / "t.json"
    rec = LLMClient(ref, transport=transport, cache=cache, mode="record", cassette=tape)
    r = rec.chat([{"role": "user", "content": "x"}])
    assert r.cached and calls == 1 and tape.exists()
    assert (
        rec.summary.total_tokens == 0 and rec.summary.cached_total_tokens == 3
    )  # original live cost is kept
    replay = LLMClient(ref, transport=transport, mode="replay", cassette=tape)
    assert replay.chat([{"role": "user", "content": "x"}]).message["content"] == "hi" and calls == 1
