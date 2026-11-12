"""Policy language and the deterministic policy engine. Design §3."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from provguard.core.provenance import Labeled, Source

Verdict = Literal["ALLOW", "CONFIRM", "DENY"]
_PRECEDENCE: dict[Verdict, int] = {"ALLOW": 0, "CONFIRM": 1, "DENY": 2}
_ALLOW_ENTRY = re.compile(r"^(USER|SYSTEM|PLANNER|tool:[A-Za-z_][\w\-]*)$")


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str | None = None
    enum: list[str | int | float | bool] | None = None
    minimum: float | None = None
    maximum: float | None = None
    exclusive: bool = False


class ArgPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    allow: list[str] = Field(default_factory=list)
    else_: Literal["CONFIRM", "DENY"] = Field(default="CONFIRM", alias="else")
    constraints: Constraints | None = None
    on_violation: Literal["CONFIRM", "DENY"] = "DENY"

    @field_validator("allow")
    @classmethod
    def _entries(cls, entries: list[str]) -> list[str]:
        for e in entries:
            if not _ALLOW_ENTRY.match(e):
                raise ValueError(f"bad allow entry {e!r} (USER, SYSTEM, PLANNER or tool:<name>)")
        return entries


DEFAULT_ARG_POLICY = ArgPolicy(allow=["USER"])


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guarded: bool = True
    default: ArgPolicy | None = None
    args: dict[str, ArgPolicy] = Field(default_factory=dict)


class PolicySet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    unlisted_tool: Literal["CONFIRM", "DENY"] = "DENY"
    tools: dict[str, ToolPolicy] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> PolicySet:
        with Path(path).open() as f:
            return cls.model_validate(yaml.safe_load(f))


class Reason(BaseModel):
    arg: str
    outcome: Verdict
    rule: str
    sources: list[str]
    message: str


class Decision(BaseModel):
    verdict: Verdict
    tool: str
    reasons: list[Reason]
    policy_version: int

    @property
    def allowed(self) -> bool:
        return self.verdict == "ALLOW"


def entry_matches(entry: str, source: Source) -> bool:
    """An allow-list entry matches a source. There is no entry that matches an untrusted source (C1)."""
    if not source.trusted:
        return False
    if entry.startswith("tool:"):
        return source.kind == "TOOL" and source.name == entry[5:]
    return source.kind == entry


def _check_constraints(c: Constraints, value: object) -> str | None:
    if c.pattern is not None and (not isinstance(value, str) or re.search(c.pattern, value) is None):
        return f"value {value!r} does not match {c.pattern!r}"
    if c.enum is not None and value not in c.enum:
        return f"value {value!r} not in {c.enum!r}"
    if c.minimum is not None or c.maximum is not None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"value {value!r} is not a number"
        if c.minimum is not None and (value <= c.minimum if c.exclusive else value < c.minimum):
            return f"value {value!r} below minimum {c.minimum}"
        if c.maximum is not None and (value >= c.maximum if c.exclusive else value > c.maximum):
            return f"value {value!r} above maximum {c.maximum}"
    return None


def _evaluate_arg(tool_name: str, arg: str, rule: ArgPolicy, value: Labeled) -> Reason:
    rule_id = f"{tool_name}.{arg}"
    sources = sorted(str(s) for s in value.all_sources())
    if rule.constraints is not None:
        problem = _check_constraints(rule.constraints, value.plain())
        if problem is not None:
            return Reason(arg=arg, outcome=rule.on_violation, rule=rule_id, sources=sources, message=problem)
    offending = sorted(
        str(s) for s in value.all_sources() if not any(entry_matches(e, s) for e in rule.allow)
    )
    if offending:
        msg = f"sources {offending} not in allowed {rule.allow}"
        return Reason(arg=arg, outcome=rule.else_, rule=rule_id, sources=sources, message=msg)
    return Reason(arg=arg, outcome="ALLOW", rule=rule_id, sources=sources, message="all sources allowed")


def decide(policy: PolicySet, tool_name: str, args: Mapping[str, Labeled]) -> Decision:
    """Deterministic, total: evaluate every present argument and combine with DENY > CONFIRM > ALLOW."""
    tp = policy.tools.get(tool_name)
    if tp is None:
        reason = Reason(
            arg="*", outcome=policy.unlisted_tool, rule="unlisted_tool", sources=[], message="no policy"
        )
        return Decision(
            verdict=policy.unlisted_tool, tool=tool_name, reasons=[reason], policy_version=policy.version
        )
    if not tp.guarded:
        reason = Reason(
            arg="*", outcome="ALLOW", rule=f"{tool_name}.unguarded", sources=[], message="unguarded"
        )
        return Decision(verdict="ALLOW", tool=tool_name, reasons=[reason], policy_version=policy.version)
    default = tp.default or DEFAULT_ARG_POLICY
    reasons = [_evaluate_arg(tool_name, arg, tp.args.get(arg, default), value) for arg, value in args.items()]
    verdict: Verdict = "ALLOW"
    for r in reasons:
        if _PRECEDENCE[r.outcome] > _PRECEDENCE[verdict]:
            verdict = r.outcome
    return Decision(verdict=verdict, tool=tool_name, reasons=reasons, policy_version=policy.version)
