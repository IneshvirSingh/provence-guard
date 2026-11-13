"""Synchronous OpenAI-compatible chat client: exact-response cache, cassette mode, retries, usage accounting.

Synchronous because AgentDojo pipelines are synchronous; the benchmark runner parallelises across tasks with
threads and the Redis-backed stores are safe to share (ADR-003).
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from provguard.llm.providers import ModelRef
from provguard.llm.quota import QuotaGuard

Mode = Literal["live", "replay", "record"]
Transport = Callable[[dict[str, Any]], dict[str, Any]]


class CassetteMiss(LookupError):
    """Replay mode found no recorded response for this exact request."""


class CacheStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value


class RedisCache:
    def __init__(self, client: object, prefix: str = "llmcache:") -> None:
        self._r = client
        self._prefix = prefix

    def get(self, key: str) -> str | None:
        raw = self._r.get(self._prefix + key)  # type: ignore[attr-defined]
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    def set(self, key: str, value: str) -> None:
        self._r.set(self._prefix + key, value)  # type: ignore[attr-defined]


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResult(BaseModel):
    message: dict[str, Any]
    usage: Usage
    cached: bool
    model: str
    key: str


class UsageSummary(BaseModel):
    requests: int = 0
    cache_hits: int = 0
    cached_prompt_tokens: int = 0  # what the cache hits cost when they were first made live
    cached_completion_tokens: int = 0
    cached_total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    retries: int = 0
    wall_seconds: float = 0.0


def cache_key(model_id: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps({"model": model_id, **payload}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def estimate_tokens(payload: Mapping[str, Any]) -> int:
    return len(json.dumps(payload, default=str)) // 4 + 64


def openai_transport(model: ModelRef, timeout: float = 120.0) -> Transport:
    import openai  # lazy: the core never imports it

    client = openai.OpenAI(base_url=model.base_url, api_key=model.api_key(), timeout=timeout, max_retries=0)

    def send(payload: dict[str, Any]) -> dict[str, Any]:
        return dict(client.chat.completions.create(**payload).model_dump())

    return send


def is_transient(exc: BaseException) -> bool:
    try:
        import openai
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, openai.RateLimitError | openai.APIConnectionError | openai.InternalServerError)


class LLMClient:
    def __init__(
        self,
        model: ModelRef,
        *,
        transport: Transport | None = None,
        cache: CacheStore | None = None,
        quota: QuotaGuard | None = None,
        mode: Mode = "live",
        cassette: Path | None = None,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        retry_predicate: Callable[[BaseException], bool] = is_transient,
    ) -> None:
        self.model = model
        self.cache = cache if cache is not None else MemoryCache()
        self.quota = quota
        self.mode = mode
        self.cassette = cassette
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._retry_predicate = retry_predicate
        self._transport = transport
        self.seed = 0  # default request seed; the benchmark sets it per run (run k uses seed k-1)
        self.summary = UsageSummary()
        self._tape: dict[str, dict[str, Any]] = {}
        if cassette is not None and cassette.exists():
            self._tape = json.loads(cassette.read_text())

    # ------------------------------------------------------------------------------------------

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        *,
        temperature: float = 0.0,
        seed: int | None = None,
        max_tokens: int | None = None,
        tool_choice: str | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model.model,
            **self.model.request_defaults,  # e.g. reasoning_effort / parallel_tool_calls from providers.yaml
            "messages": [dict(m) for m in messages],
            "temperature": temperature,
            "seed": self.seed if seed is None else seed,
        }
        if tools:
            payload["tools"] = [dict(t) for t in tools]
            payload["tool_choice"] = tool_choice or "auto"
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = dict(response_format)
        key = cache_key(self.model.id, payload)

        hit = self.cache.get(key)
        raw: dict[str, Any] | None = json.loads(hit) if hit is not None else self._tape.get(key)
        if raw is not None:
            self.summary.cache_hits += 1
            hit_usage = Usage.model_validate(raw.get("usage") or {})
            self.summary.cached_prompt_tokens += hit_usage.prompt_tokens
            self.summary.cached_completion_tokens += hit_usage.completion_tokens
            self.summary.cached_total_tokens += hit_usage.total_tokens
            self._record(key, raw)  # a cache hit still belongs in the cassette
            return self._result(raw, key, cached=True)
        if self.mode == "replay":
            raise CassetteMiss(f"no recorded response for request {key[:12]} (model {self.model.id})")

        raw = self._send(payload)
        self.cache.set(key, json.dumps(raw))
        self._record(key, raw)
        return self._result(raw, key, cached=False)

    def _record(self, key: str, raw: dict[str, Any]) -> None:
        if self.mode != "record" or self.cassette is None or key in self._tape:
            return
        self._tape[key] = raw
        self.cassette.parent.mkdir(parents=True, exist_ok=True)
        self.cassette.write_text(json.dumps(self._tape, indent=1, sort_keys=True))

    # ------------------------------------------------------------------------------------------

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._transport is None:
            self._transport = openai_transport(self.model)
        estimate = estimate_tokens(payload)
        if self.quota is not None:
            self.quota.acquire(estimate)
        started = self._clock()
        attempt = 0
        while True:
            try:
                raw = self._transport(payload)
                break
            except Exception as exc:
                if attempt >= self.max_retries or not self._retry_predicate(exc):
                    raise
                attempt += 1
                self.summary.retries += 1
                self._sleep(min(60.0, (2**attempt) + random.uniform(0, 1)))  # noqa: S311 - jitter, not crypto
        usage = Usage.model_validate(raw.get("usage") or {})
        self.summary.requests += 1
        self.summary.prompt_tokens += usage.prompt_tokens
        self.summary.completion_tokens += usage.completion_tokens
        self.summary.total_tokens += usage.total_tokens
        self.summary.wall_seconds += self._clock() - started
        if self.quota is not None:
            self.quota.settle(estimate, usage.total_tokens)
        return raw

    def _result(self, raw: Mapping[str, Any], key: str, *, cached: bool) -> ChatResult:
        choices = raw.get("choices") or []
        if not choices:
            raise ValueError("response has no choices")
        message = dict(choices[0]["message"])
        return ChatResult(
            message=message,
            usage=Usage.model_validate(raw.get("usage") or {}),
            cached=cached,
            model=str(raw.get("model") or self.model.model),
            key=key,
        )


__all__ = [
    "CacheStore",
    "CassetteMiss",
    "ChatResult",
    "LLMClient",
    "MemoryCache",
    "Mode",
    "RedisCache",
    "Transport",
    "Usage",
    "UsageSummary",
    "cache_key",
    "estimate_tokens",
    "openai_transport",
]
