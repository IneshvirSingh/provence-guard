"""Plan schema and static validation. Design §1."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from provguard.core.provenance import Cmp, Fn, ReduceFn, Scalar

MAX_STEPS = 20
MAX_ITEMS = 25


class PlanError(ValueError):
    """A plan failed static validation."""


class Lit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lit: Scalar


class Ref(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str
    path: str = ""


Value = Lit | Ref


class FieldSpec(BaseModel):
    """Target schema for one extracted field."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["str", "int", "float", "bool"]
    pattern: str | None = None
    enum: list[Scalar] | None = None
    minimum: float | None = None
    maximum: float | None = None
    description: str | None = None


class CallTool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["call"]
    out: str
    tool: str
    args: dict[str, Value] = Field(default_factory=dict)


class Select(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["select"]
    out: str
    ref: str
    path: str


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["filter"]
    out: str
    ref: str
    field: str
    cmp: Cmp
    value: Value


class Compute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["compute"]
    out: str
    fn: Fn
    a: Value
    b: Value


class Reduce(BaseModel):
    """Aggregate a list of numbers (or count any list) deterministically."""

    model_config = ConfigDict(extra="forbid")
    op: Literal["reduce"]
    out: str
    ref: str
    fn: ReduceFn
    path: str = ""  # sugar: select this field of each item first (``{"ref": "tx", "path": "amount"}``)


class Extract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    op: Literal["extract"]
    out: str
    from_: list[Ref] = Field(alias="from", min_length=1)
    instruction: str
    schema_: dict[str, FieldSpec] = Field(alias="schema", min_length=1)


class Respond(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["respond"]
    template: str


BodyStep = Annotated[CallTool | Select | Filter | Compute | Reduce | Extract, Field(discriminator="op")]


class ForEach(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["foreach"]
    out: str
    ref: str
    max_items: int = Field(ge=1, le=MAX_ITEMS)
    steps: list[BodyStep] = Field(min_length=1)


Step = Annotated[
    CallTool | Select | Filter | Compute | Reduce | Extract | ForEach | Respond, Field(discriminator="op")
]


class ToolSpec(BaseModel):
    """What the validator knows about a tool: its argument names and which are required."""

    model_config = ConfigDict(extra="forbid")
    name: str
    args: dict[str, bool] = Field(default_factory=dict, description="arg name -> required")
    description: str = ""
    returns: str = ""  # output schema shown to the planner (never data); see policies/schemas/


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[Step] = Field(min_length=1, max_length=MAX_STEPS)

    @model_validator(mode="after")
    def _respond_last(self) -> Plan:
        for i, step in enumerate(self.steps):
            if isinstance(step, Respond) and i != len(self.steps) - 1:
                raise ValueError("respond must be the last step")
        return self

    def validate_against(self, tools: Mapping[str, ToolSpec]) -> None:
        """Static checks beyond the schema: scoping, tool names and arguments. Raises PlanError."""
        scope: set[str] = set()
        for step in self.steps:
            _check_step(step, scope, tools, in_loop=False)


def _use(name: str, scope: set[str]) -> None:
    if name not in scope:
        raise PlanError(f"ref {name!r} is not defined by an earlier step")


def _use_value(v: Value, scope: set[str]) -> None:
    if isinstance(v, Ref):
        _use(v.ref, scope)


def _define(name: str, scope: set[str]) -> None:
    if name in scope or name == "item":
        raise PlanError(f"out name {name!r} is already defined")
    scope.add(name)


def _check_step(
    step: Step | BodyStep, scope: set[str], tools: Mapping[str, ToolSpec], *, in_loop: bool
) -> None:
    if isinstance(step, CallTool):
        spec = tools.get(step.tool)
        if spec is None:
            raise PlanError(f"unknown tool {step.tool!r}")
        for name in step.args:
            if name not in spec.args:
                raise PlanError(f"tool {step.tool!r} has no argument {name!r}")
        for name, required in spec.args.items():
            if required and name not in step.args:
                raise PlanError(f"tool {step.tool!r} requires argument {name!r}")
        for v in step.args.values():
            _use_value(v, scope)
        _define(step.out, scope)
    elif isinstance(step, Select | Reduce):
        _use(step.ref, scope)
        _define(step.out, scope)
    elif isinstance(step, Filter):
        _use(step.ref, scope)
        _use_value(step.value, scope)
        _define(step.out, scope)
    elif isinstance(step, Compute):
        _use_value(step.a, scope)
        _use_value(step.b, scope)
        _define(step.out, scope)
    elif isinstance(step, Extract):
        for r in step.from_:
            _use(r.ref, scope)
        _define(step.out, scope)
    elif isinstance(step, ForEach):
        if in_loop:
            raise PlanError("nested foreach is not allowed")
        _use(step.ref, scope)
        inner = set(scope) | {"item"}
        for body in step.steps:
            _check_step(body, inner, tools, in_loop=True)
        _define(step.out, scope)
    elif isinstance(step, Respond):
        return
