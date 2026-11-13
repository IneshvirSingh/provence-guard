"""Provider registry backed by config/providers.yaml. Enforces master-prompt rule 4 (₹0).

A provider is usable only if it is listed, ``enabled`` and ``requires_payment_method`` is exactly ``false``.
Model IDs are never trusted from memory: :meth:`ProviderRegistry.check_models` compares the configured IDs
with the provider's live ``GET /models`` list (OpenAI-compatible; verified against Groq 2026-11-13).
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "providers.yaml"


class ProviderError(RuntimeError):
    """The provider is unknown, not verified payment-free, or missing its key."""


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rpm: int | None = None
    rpd: int | None = None
    tpm: int | None = None
    tpd: int | None = None

    def complete(self) -> bool:
        return None not in (self.rpm, self.rpd, self.tpm, self.tpd)


ModelKind = Literal["agent", "classifier"]


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ModelKind = "agent"
    tool_calling: bool = True
    parallel_tool_calls: bool = False
    json_mode: bool = False
    context_window: int | None = None
    request_defaults: dict[str, Any] = Field(default_factory=dict)
    limits: Limits = Field(default_factory=Limits)
    limits_source: str | None = None


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    base_url: str
    api_key_env: str
    requires_payment_method: bool | None = None
    data_used_for_training: bool | None = None
    models: dict[str, ModelConfig] = Field(default_factory=dict)


class ModelRef(BaseModel):
    """A resolved ``provider/model`` pair with everything the client needs."""

    model_config = ConfigDict(frozen=True)
    provider: str
    model: str
    base_url: str
    api_key_env: str
    limits: Limits
    kind: ModelKind = "agent"
    tool_calling: bool = True
    request_defaults: dict[str, Any] = Field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.provider}/{self.model}"

    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ProviderError(f"environment variable {self.api_key_env} is not set (Codespaces secret)")
        return key


ModelsFetcher = Callable[[str, Mapping[str, str]], dict[str, Any]]


class ProviderRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providers: dict[str, ProviderConfig]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> ProviderRegistry:
        with Path(path).open() as f:
            return cls.model_validate(yaml.safe_load(f))

    def resolve(self, ref: str) -> ModelRef:
        """``provider/model`` -> ModelRef, refusing anything that could cost money."""
        provider_name, sep, model = ref.partition("/")
        if not sep or not model:
            raise ProviderError(f"model reference must look like provider/model, got {ref!r}")
        provider = self.providers.get(provider_name)
        if provider is None:
            raise ProviderError(f"provider {provider_name!r} is not in config/providers.yaml")
        if not provider.enabled:
            raise ProviderError(f"provider {provider_name!r} is disabled in config/providers.yaml")
        if provider.requires_payment_method is not False:
            raise ProviderError(
                f"provider {provider_name!r} is not verified payment-free "
                "(requires_payment_method must be false)"
            )
        if model not in provider.models:
            raise ProviderError(f"model {model!r} is not listed under provider {provider_name!r}")
        return ModelRef(
            provider=provider_name,
            model=model,
            base_url=provider.base_url,
            api_key_env=provider.api_key_env,
            limits=provider.models[model].limits,
            kind=provider.models[model].kind,
            tool_calling=provider.models[model].tool_calling,
            request_defaults=dict(provider.models[model].request_defaults),
        )

    def check_models(self, provider_name: str, fetch: ModelsFetcher | None = None) -> set[str]:
        """Fail clearly if any configured model ID is missing from the provider's live ``/models`` list.

        Returns the set of live IDs. ``fetch`` is injectable for tests; the default does a plain HTTPS GET.
        """
        provider = self.providers.get(provider_name)
        if provider is None:
            raise ProviderError(f"provider {provider_name!r} is not in config/providers.yaml")
        if not provider.enabled:
            raise ProviderError(f"provider {provider_name!r} is disabled in config/providers.yaml")
        key = os.environ.get(provider.api_key_env, "")
        if not key:
            raise ProviderError(f"environment variable {provider.api_key_env} is not set (Codespaces secret)")
        url = provider.base_url.rstrip("/") + "/models"
        body = (fetch or _http_get_json)(url, {"Authorization": f"Bearer {key}"})
        live = {str(m["id"]) for m in body.get("data", []) if isinstance(m, Mapping) and "id" in m}
        if not live:
            raise ProviderError(f"{provider_name}: {url} returned no model list (keys: {sorted(body)})")
        missing = sorted(set(provider.models) - live)
        if missing:
            raise ProviderError(
                f"{provider_name}: configured model(s) not offered by {url}: {missing}. "
                f"Live IDs: {sorted(live)}. Fix config/providers.yaml; never write model IDs from memory."
            )
        return live


USER_AGENT = (
    "provguard/0.1"  # Groq's edge returns 403 to urllib's default "Python-urllib/x.y" (seen 2026-11-13)
)


def _http_get_json(url: str, headers: Mapping[str, str], timeout: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})  # noqa: S310 - our config
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return dict(json.loads(resp.read().decode()))
