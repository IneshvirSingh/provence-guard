"""Planner (P-LLM): one request -> one validated :class:`provguard.core.Plan`. Never sees tool outputs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from provguard.agent.prompts import planner_messages
from provguard.core.plan import Plan, PlanError, ToolSpec
from provguard.llm.client import LLMClient

JSON_OBJECT = {"type": "json_object"}
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def is_generation_failure(exc: BaseException) -> bool:
    """Provider-side 400 for JSON mode (Groq: "Failed to generate JSON", seen 2026-11-13). Not transient."""
    return getattr(exc, "status_code", None) == 400


class PlannerError(RuntimeError):
    """No valid plan after the allowed attempts; the agent fails closed."""


class PlanResult(BaseModel):
    plan: Plan
    attempts: int
    raw: str


def parse_plan(text: str, tools: Mapping[str, ToolSpec]) -> Plan:
    m = _FENCE.match(text)
    body = m.group(1) if m else text
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise PlanError(f"not JSON: {e}") from e
    if isinstance(data, list):
        data = {"steps": data}
    try:
        plan = Plan.model_validate(data)
    except ValidationError as e:
        raise PlanError(f"schema: {e.errors()[0].get('msg')} at {e.errors()[0].get('loc')}") from e
    plan.validate_against(tools)
    return plan


def render_tools(tools: Mapping[str, ToolSpec], types: Mapping[str, str] | None = None) -> str:
    lines = []
    for spec in tools.values():
        args = ", ".join(f"{a}{'' if req else '?'}" for a, req in spec.args.items())
        line = f"- {spec.name}({args}): {spec.description}".rstrip(": ")
        lines.append(f"{line}\n    returns: {spec.returns}" if spec.returns else line)
    out = "\n".join(lines) or "(no tools)"
    if types:
        out += "\n\n## Result types\n" + "\n".join(f"- {name}: {text}" for name, text in types.items())
    return out


class Planner:
    def __init__(
        self,
        client: LLMClient,
        *,
        max_attempts: int = 2,
        temperature: float = 0.0,
        types: Mapping[str, str] | None = None,
    ) -> None:
        self.client = client
        self.types = dict(types or {})
        self.max_attempts = max_attempts
        self.temperature = temperature

    def plan(self, prompt: str, tools: Mapping[str, ToolSpec]) -> PlanResult:
        messages: list[dict[str, Any]] = list(planner_messages(prompt, render_tools(tools, self.types)))
        last_error = "no attempt made"
        raw = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = self.client.chat(messages, temperature=self.temperature, response_format=JSON_OBJECT)
            except Exception as e:
                if not is_generation_failure(e):
                    raise
                raw, last_error = "", "the provider could not generate valid JSON"
                messages += [{"role": "user", "content": "Return one valid JSON object for the plan."}]
                continue
            raw = str(result.message.get("content") or "")
            try:
                return PlanResult(plan=parse_plan(raw, tools), attempts=attempt, raw=raw)
            except PlanError as e:
                last_error = str(e)
                messages += [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": f"That plan was rejected: {last_error}. Return a corrected plan.",
                    },
                ]
        raise PlannerError(f"no valid plan after {self.max_attempts} attempts: {last_error}")


__all__ = [
    "JSON_OBJECT",
    "PlanResult",
    "Planner",
    "PlannerError",
    "is_generation_failure",
    "parse_plan",
    "render_tools",
]
