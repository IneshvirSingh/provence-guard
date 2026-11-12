"""Provider registry backed by config/providers.yaml. Enforces master-prompt rule 4 (₹0).

A provider is usable only if it is listed and ``requires_payment_method`` is explicitly ``false``.
"""

from __future__ import annotations

import os
from pathlib import Path

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


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_calling: bool = True
    parallel_tool_calls: bool = False
    json_mode: bool = False
    limits: Limits = Field(default_factory=Limits)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
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

    @property
    def id(self) -> str:
        return f"{self.provider}/{self.model}"

    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ProviderError(f"environment variable {self.api_key_env} is not set (Codespaces secret)")
        return key


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
        )
