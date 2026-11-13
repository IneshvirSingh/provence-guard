"""AgentDojo adapter: a ``BasePipelineElement`` that plans, mediates every tool call through the policy
engine, and emits AgentDojo-format messages so trace- and state-based checks keep working (recon §7, ADR-004).
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.functions_runtime import EmptyEnv, Env, Function, FunctionCall, FunctionsRuntime
from agentdojo.types import (
    ChatAssistantMessage,
    ChatMessage,
    ChatToolResultMessage,
    text_content_block_from_string,
)
from pydantic import BaseModel

from provguard.agent.extractor import LLMExtractor
from provguard.agent.planner import Planner, PlannerError
from provguard.core.plan import ToolSpec
from provguard.core.policy import Decision, PolicySet
from provguard.core.runner import (
    ConfirmHandler,
    ExtractorCallable,
    PlanRunner,
    PlanRuntimeError,
    RunResult,
    confirm_permissive,
    confirm_strict,
)
from provguard.core.trust import TrustConfig
from provguard.llm.client import LLMClient

Mode = Literal["strict", "permissive"]
POLICY_DIR = Path(__file__).resolve().parents[3] / "policies"
GUARD_SYSTEM_MESSAGE = (
    "You are an AI language model who assists the user by using the given tools. Every tool call is planned "
    "up front and checked against a provenance policy before it runs."
)


class ToolSchemas(BaseModel):
    """Planner-facing output schemas (``policies/schemas/<suite>.yaml``): tool semantics, never data."""

    version: int = 1
    types: dict[str, str] = {}
    tools: dict[str, dict[str, str]] = {}

    @classmethod
    def load(cls, path: Path) -> ToolSchemas:
        return cls.model_validate(yaml.safe_load(path.read_text()))

    def returns(self, tool: str) -> str:
        return " ".join(self.tools.get(tool, {}).get("returns", "").split())


def tool_specs(functions: Sequence[Function], schemas: ToolSchemas | None = None) -> dict[str, ToolSpec]:
    """AgentDojo ``Function`` -> planner/validator ``ToolSpec`` (names, required args, short description)."""
    specs: dict[str, ToolSpec] = {}
    for f in functions:
        schema = f.parameters.model_json_schema()
        required = set(schema.get("required") or [])
        props: dict[str, Any] = schema.get("properties") or {}
        args = {name: name in required for name in props}
        params = "; ".join(
            f"{name}: {_type_of(p)}" + (f" - {p['description']}" if p.get("description") else "")
            for name, p in props.items()
        )
        desc = " ".join(str(f.description).split())
        specs[f.name] = ToolSpec(
            name=f.name,
            args=args,
            description=f"{desc} [{params}]" if params else desc,
            returns=schemas.returns(f.name) if schemas else "",
        )
    return specs


def _type_of(prop: dict[str, Any]) -> str:
    if "type" in prop:
        return str(prop["type"])
    if "anyOf" in prop:
        return "|".join(str(o.get("type", "?")) for o in prop["anyOf"])
    return "any"


def today_from_env(env: Any, clock: Callable[[], dt.date] = dt.date.today) -> tuple[str, str]:
    """Today's date the way a deployed system would read it: the environment's own clock if it has one
    (AgentDojo suites with a calendar expose ``calendar.current_day``), otherwise the process clock.

    The banking environment defines no current date anywhere (verified in agentdojo==0.1.35: no clock field,
    tool or system-message date), so banking runs use the real clock. Returns (iso date, where it came from).
    """
    current = getattr(getattr(env, "calendar", None), "current_day", None)
    if isinstance(current, dt.date):
        return current.isoformat(), "env.calendar.current_day"
    return clock().isoformat(), "process clock"


class GuardTrace(BaseModel):
    """What one request did, for logs and tests (also placed in ``extra_args['provguard']``)."""

    plan: dict[str, Any] | None = None
    planner_attempts: int = 0
    result: RunResult | None = None
    failure: str | None = None
    today: str | None = None
    today_source: str | None = None


class ProvenanceGuard(BasePipelineElement):
    """Plan -> policy-mediated execution -> response, inside an AgentDojo pipeline."""

    def __init__(
        self,
        client: LLMClient,
        *,
        trust: TrustConfig,
        policy: PolicySet,
        mode: Mode = "strict",
        schemas: ToolSchemas | None = None,
        planner: Planner | None = None,
        extractor: ExtractorCallable | None = None,
        confirm: ConfirmHandler | None = None,
        clock: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        self.clock = clock
        self.client = client
        self.trust = trust
        self.policy = policy
        self.mode = mode
        self.schemas = schemas
        types = {k: " ".join(v.split()) for k, v in schemas.types.items()} if schemas else None
        self.planner = planner or Planner(client, types=types)
        self.extractor = extractor or LLMExtractor(client)
        self.confirm = confirm or (confirm_strict if mode == "strict" else confirm_permissive)
        variant = (
            mode if schemas is not None else f"{mode}-noschema"
        )  # separate AgentDojo log dirs per variant
        self.name = f"provguard-{variant}-{client.model.id.replace('/', '_')}"
        self.last: GuardTrace | None = None
        self.history: list[GuardTrace] = []  # one entry per request served by this element

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),  # noqa: B008 - AgentDojo's signature
        messages: Sequence[ChatMessage] = [],
        extra_args: dict[str, Any] = {},  # noqa: B006 - AgentDojo's signature
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict[str, Any]]:
        out: list[ChatMessage] = list(messages)
        trace = GuardTrace()
        trace.today, trace.today_source = today_from_env(env, self.clock)
        specs = tool_specs(list(runtime.functions.values()), self.schemas)

        try:
            planned = self.planner.plan(query, specs)
        except PlannerError as e:
            trace.failure = str(e)
            out.append(
                _assistant(f"I could not produce a valid plan for this request, so I did nothing. ({e})")
            )
            return self._finish(query, runtime, env, out, extra_args, trace)
        trace.plan = planned.plan.model_dump(by_alias=True, exclude_none=True)
        trace.planner_attempts = planned.attempts
        out.append(_assistant("Plan:\n```json\n" + json.dumps(trace.plan, indent=1) + "\n```"))

        counter = {"n": 0}

        def call_tool(name: str, args: dict[str, Any]) -> Any:
            counter["n"] += 1
            call = FunctionCall(function=name, args=dict(args), id=f"call_{counter['n']}")
            out.append(ChatAssistantMessage(role="assistant", content=None, tool_calls=[call]))
            result, error = runtime.run_function(env, name, args)
            out.append(
                ChatToolResultMessage(
                    role="tool",
                    tool_call=call,
                    tool_call_id=call.id,
                    content=[text_content_block_from_string(error if error else tool_result_to_str(result))],
                    error=error,
                )
            )
            if error:
                raise PlanRuntimeError(f"{name}: {error}")
            return result

        runner = PlanRunner(
            trust=self.trust,
            policy=self.policy,
            tools=specs,
            call_tool=call_tool,
            extractor=self.extractor,
            confirm=self.confirm,
            prompt=query,
            system_values={"today": trace.today},
        )
        result = runner.run(planned.plan)  # tool errors raised in call_tool end the run with status "error"
        trace.result = result
        out.append(_assistant(self._final_text(result)))
        return self._finish(query, runtime, env, out, extra_args, trace)

    def _final_text(self, result: RunResult) -> str:
        if result.status == "ok":
            return result.response or "Done."
        if result.status == "denied":
            rec = next((r for r in reversed(result.records) if r.decision is not None), None)
            if rec is None or rec.decision is None:
                return "I did not perform the requested action because the policy did not allow it."
            return _explain(rec.decision, rec.confirmed)
        last = result.records[-1] if result.records else None
        return f"I stopped before finishing: {last.error if last else 'unknown error'}"

    def _finish(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env,
        out: list[ChatMessage],
        extra_args: dict[str, Any],
        trace: GuardTrace,
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict[str, Any]]:
        self.last = trace
        self.history.append(trace)
        return query, runtime, env, out, {**extra_args, "provguard": trace.model_dump()}


def _assistant(text: str) -> ChatAssistantMessage:
    return ChatAssistantMessage(
        role="assistant", content=[text_content_block_from_string(text)], tool_calls=None
    )


def _explain(decision: Decision, confirmed: bool | None) -> str:
    reasons = [r for r in decision.reasons if r.outcome != "ALLOW"]
    why = "; ".join(f"{r.arg}: {r.message}" for r in reasons) or "policy"
    if decision.verdict == "CONFIRM" and confirmed is False:
        return (
            f"I did not call {decision.tool}: its arguments come from data I cannot verify ({why}). "
            "Please confirm them explicitly if you want me to proceed."
        )
    return f"I did not call {decision.tool}: the policy denied it ({why})."


def build_guard_pipeline(
    client: LLMClient,
    mode: Mode = "strict",
    *,
    suite: str = "banking",
    trust_path: Path | None = None,
    policy_path: Path | None = None,
    extractor_client: LLMClient | None = None,
    use_schemas: bool = True,
) -> AgentPipeline:
    trust = TrustConfig.load(trust_path or POLICY_DIR / "trust.yaml")
    policy = PolicySet.load(policy_path or POLICY_DIR / f"{suite}.yaml")
    schema_path = POLICY_DIR / "schemas" / f"{suite}.yaml"
    guard = ProvenanceGuard(
        client,
        trust=trust,
        policy=policy,
        mode=mode,
        schemas=ToolSchemas.load(schema_path) if use_schemas and schema_path.exists() else None,
        extractor=LLMExtractor(extractor_client) if extractor_client is not None else None,
    )
    pipeline = AgentPipeline([SystemMessage(GUARD_SYSTEM_MESSAGE), InitQuery(), guard])
    pipeline.name = guard.name
    return pipeline


def _is_guarded(decision: Decision | None) -> bool:
    return decision is not None and not any(r.rule.endswith(".unguarded") for r in decision.reasons)


def guard_stats(history: Sequence[GuardTrace]) -> dict[str, Any]:
    """Aggregate what the guard did over the requests it served in this process (resumed cases are absent)."""
    results = [t.result for t in history if t.result is not None]
    statuses: dict[str, int] = {}
    for t in history:
        key = t.result.status if t.result is not None else "planner_failed"
        statuses[key] = statuses.get(key, 0) + 1
    return {
        "requests": len(history),
        "requests_reaching_guarded_call": sum(
            1 for r in results if any(_is_guarded(rec.decision) for rec in r.records)
        ),
        "requests_with_confirmation": sum(1 for r in results if r.confirmations > 0),
        "confirmations": sum(r.confirmations for r in results),
        "tool_calls_executed": sum(len(r.tool_calls) for r in results),
        "statuses": statuses,
    }


__all__ = [
    "GuardTrace",
    "Mode",
    "ProvenanceGuard",
    "ToolSchemas",
    "build_guard_pipeline",
    "guard_stats",
    "tool_specs",
]
