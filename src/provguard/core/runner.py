"""PlanRunner: executes a validated plan with injected tool/extractor/confirmation callables.

This is the single point of complete mediation (threat model claim C4): every CallTool goes through
:func:`provguard.core.policy.decide` before the tool callable is invoked. No I/O happens here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from provguard.core.extraction import ExtractionError, validate_extraction
from provguard.core.plan import (
    BodyStep,
    CallTool,
    Compute,
    Extract,
    FieldSpec,
    Filter,
    ForEach,
    Lit,
    Plan,
    Reduce,
    Ref,
    Respond,
    Select,
    Step,
    Sys,
    ToolSpec,
    Value,
)
from provguard.core.policy import Decision, PolicySet, decide
from provguard.core.provenance import (
    PLANNER,
    SYSTEM,
    Labeled,
    ProvenanceError,
    compute,
    extracted,
    filter_items,
    ground_literal,
    reduce_items,
    scalar,
    select,
    union,
)
from provguard.core.trust import TrustConfig

ToolCallable = Callable[[str, dict[str, Any]], Any]
ExtractorCallable = Callable[[list[Any], str, Mapping[str, FieldSpec]], Any]
ConfirmHandler = Callable[[Decision, dict[str, Any]], bool]


def confirm_strict(decision: Decision, args: dict[str, Any]) -> bool:
    """CONFIRM -> deny. The benchmark's lower bound on utility."""
    return False


def confirm_permissive(decision: Decision, args: dict[str, Any]) -> bool:
    """CONFIRM -> approve. The benchmark's upper bound on attack success (a careless user)."""
    return True


class StepRecord(BaseModel):
    index: int
    op: str
    out: str | None = None
    tool: str | None = None
    decision: Decision | None = None
    confirmed: bool | None = None
    executed: bool = False
    error: str | None = None


class RunResult(BaseModel):
    status: str  # "ok" | "denied" | "error"
    response: str | None = None
    records: list[StepRecord] = Field(default_factory=list)
    confirmations: int = 0

    @property
    def tool_calls(self) -> list[StepRecord]:
        return [r for r in self.records if r.tool is not None and r.executed]


class PlanRuntimeError(RuntimeError):
    """A step failed at run time; the run stops (fail closed)."""


class PlanRunner:
    def __init__(
        self,
        *,
        trust: TrustConfig,
        policy: PolicySet,
        tools: Mapping[str, ToolSpec],
        call_tool: ToolCallable,
        extractor: ExtractorCallable,
        confirm: ConfirmHandler = confirm_strict,
        prompt: str = "",
        extract_retries: int = 1,
        system_values: Mapping[str, Any] | None = None,
    ) -> None:
        self.system_values = dict(system_values or {})
        self.trust = trust
        self.policy = policy
        self.tools = tools
        self.call_tool = call_tool
        self.extractor = extractor
        self.confirm = confirm
        self.prompt = prompt
        self.extract_retries = extract_retries

    def run(self, plan: Plan) -> RunResult:
        plan.validate_against(self.tools)
        bindings: dict[str, Labeled] = {}
        result = RunResult(status="ok")
        try:
            for i, step in enumerate(plan.steps):
                record = StepRecord(index=i, op=step.op)
                result.records.append(record)
                if isinstance(step, Respond):
                    result.response = self._respond(step, bindings)
                    record.executed = True
                elif isinstance(step, ForEach):
                    self._foreach(step, bindings, record, result)
                elif not self._body_step(step, bindings, record, result):
                    result.status = "denied"
                    return result
        except (ProvenanceError, ExtractionError, PlanRuntimeError) as e:
            result.records[-1].error = f"{type(e).__name__}: {e}"
            result.status = "error"
        return result

    # -- steps -------------------------------------------------------------------------------------

    def _body_step(
        self, step: BodyStep, bindings: dict[str, Labeled], rec: StepRecord, res: RunResult
    ) -> bool:
        """Run one non-control step. Returns False if the run must stop (DENY or unconfirmed CONFIRM)."""
        rec.out = step.out
        if isinstance(step, CallTool):
            return self._call(step, bindings, rec, res)
        if isinstance(step, Select):
            bindings[step.out] = select(bindings[step.ref], step.path)
        elif isinstance(step, Filter):
            bindings[step.out] = filter_items(
                bindings[step.ref], step.field, step.cmp, self._value(step.value, bindings)
            )
        elif isinstance(step, Compute):
            bindings[step.out] = compute(
                step.fn, self._value(step.a, bindings), self._value(step.b, bindings)
            )
        elif isinstance(step, Reduce):
            bindings[step.out] = reduce_items(select(bindings[step.ref], step.path), step.fn)
        else:
            bindings[step.out] = self._extract(step, bindings)
        rec.executed = True
        return True

    def _call(self, step: CallTool, bindings: dict[str, Labeled], rec: StepRecord, res: RunResult) -> bool:
        rec.tool = step.tool
        args = {name: self._value(v, bindings) for name, v in step.args.items()}
        plain = {name: v.plain() for name, v in args.items()}
        decision = decide(self.policy, step.tool, args)
        rec.decision = decision
        if decision.verdict == "DENY":
            return False
        if decision.verdict == "CONFIRM":
            res.confirmations += 1
            rec.confirmed = bool(self.confirm(decision, plain))
            if not rec.confirmed:
                return False
        raw = self.call_tool(step.tool, plain)
        rec.executed = True
        bindings[step.out] = self.trust.label_output(
            step.tool, raw, union(*(v.all_sources() for v in args.values()))
        )
        return True

    def _extract(self, step: Extract, bindings: dict[str, Labeled]) -> Labeled:
        inputs = [select(bindings[r.ref], r.path) for r in step.from_]
        instruction = scalar(step.instruction, ground_literal(step.instruction, self.prompt))
        plain_inputs = [i.plain() for i in inputs]
        last: ExtractionError | None = None
        for _ in range(self.extract_retries + 1):
            raw = self.extractor(plain_inputs, step.instruction, step.schema_)
            try:
                return extracted(validate_extraction(step.schema_, raw), inputs, instruction)
            except ExtractionError as e:
                last = e
        raise last if last is not None else PlanRuntimeError("extractor failed")

    def _foreach(self, step: ForEach, bindings: dict[str, Labeled], rec: StepRecord, res: RunResult) -> None:
        source = bindings[step.ref]
        if not isinstance(source.value, tuple):
            raise PlanRuntimeError("foreach needs a list")
        collected: list[Labeled] = []
        for item in source.value[: step.max_items]:
            local = dict(bindings)
            local["item"] = Labeled(item.value, item.sources | source.sources)
            last_out: str | None = None
            for body in step.steps:
                sub = StepRecord(index=rec.index, op=body.op)
                res.records.append(sub)
                if not self._body_step(body, local, sub, res):
                    raise PlanRuntimeError(f"step {body.op} in foreach was not allowed")
                last_out = body.out
            if last_out is not None:
                collected.append(local[last_out])
        bindings[step.out] = Labeled(
            tuple(collected), union(*(c.sources for c in collected)) if collected else frozenset()
        )
        rec.out = step.out
        rec.executed = True

    def _respond(self, step: Respond, bindings: dict[str, Labeled]) -> str:
        try:
            return step.template.format_map({k: v.plain() for k, v in bindings.items()})
        except (KeyError, IndexError, ValueError, AttributeError, TypeError) as e:
            raise PlanRuntimeError(f"bad respond template: {e}") from e

    # -- values ------------------------------------------------------------------------------------

    def _value(self, v: Value, bindings: dict[str, Labeled]) -> Labeled:
        if isinstance(v, Lit):
            return scalar(v.lit, ground_literal(v.lit, self.prompt) if self.prompt else PLANNER)
        if isinstance(v, Sys):
            if v.sys not in self.system_values:
                raise PlanRuntimeError(f"system value {v.sys!r} is not available")
            return scalar(self.system_values[v.sys], SYSTEM)
        ref: Ref = v
        return select(bindings[ref.ref], ref.path)


__all__ = [
    "ConfirmHandler",
    "ExtractorCallable",
    "PlanRunner",
    "PlanRuntimeError",
    "RunResult",
    "Step",
    "StepRecord",
    "ToolCallable",
    "confirm_permissive",
    "confirm_strict",
]
