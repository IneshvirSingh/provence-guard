"""Trust configuration (policies/trust.yaml) and labelling of tool outputs. Design §2.3."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from provguard.core.provenance import Labeled, Source, Sources, tool

TrustLevel = Literal["trusted", "untrusted"]


class ToolTrust(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trusted: bool
    fields: dict[str, TrustLevel] = Field(default_factory=dict)
    echoes_args: bool = False
    sensitive: bool = False


class TrustConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    default: TrustLevel = "untrusted"
    tools: dict[str, ToolTrust] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> TrustConfig:
        with Path(path).open() as f:
            return cls.model_validate(yaml.safe_load(f))

    def trust_for(self, tool_name: str) -> ToolTrust:
        return self.tools.get(tool_name, ToolTrust(trusted=self.default == "trusted"))

    def label_output(self, tool_name: str, raw: Any, arg_sources: Iterable[Source] = ()) -> Labeled:
        """Label a tool's raw output per the config: whole-output trust, per-field overrides, echoed args."""
        cfg = self.trust_for(tool_name)
        echo: Sources = frozenset(arg_sources) if cfg.echoes_args else frozenset()
        base = frozenset({tool(tool_name, cfg.trusted)}) | echo
        overrides = {
            name: frozenset({tool(tool_name, level == "trusted")}) | echo
            for name, level in cfg.fields.items()
        }
        return _label(_dump(raw), base, overrides)


def _dump(raw: Any) -> Any:
    if isinstance(raw, BaseModel):
        return raw.model_dump()
    if isinstance(raw, Mapping):
        return {str(k): _dump(v) for k, v in raw.items()}
    if isinstance(raw, list | tuple):
        return [_dump(v) for v in raw]
    return raw


def _label(raw: Any, sources: Sources, overrides: Mapping[str, Sources]) -> Labeled:
    if isinstance(raw, dict):
        return Labeled({k: _label(v, overrides.get(k, sources), overrides) for k, v in raw.items()}, sources)
    if isinstance(raw, list):
        return Labeled(tuple(_label(v, sources, overrides) for v in raw), sources)
    if raw is None or isinstance(raw, str | int | float | bool):
        return Labeled(raw, sources)
    return Labeled(str(raw), sources)
