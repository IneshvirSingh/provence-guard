"""Provenance: sources, labelled values and the label-carrying deterministic operations.

See docs/design/core.md §2. Nothing in this module ever removes a source.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

Kind = Literal["USER", "SYSTEM", "PLANNER", "TOOL"]
Scalar = str | int | float | bool | None
Cmp = Literal["eq", "ne", "lt", "le", "gt", "ge", "contains"]
Fn = Literal["add", "sub", "mul", "div"]
ReduceFn = Literal["sum", "count", "min", "max"]


class ProvenanceError(ValueError):
    """Raised when a label-carrying operation cannot be performed (bad path, bad types)."""


@dataclass(frozen=True, slots=True)
class Source:
    """Where a value came from. ``trusted`` is only meaningful for TOOL sources (decided by trust.yaml)."""

    kind: Kind
    name: str | None = None
    trusted: bool = True

    def __post_init__(self) -> None:
        if self.kind == "TOOL":
            if not self.name:
                raise ValueError("TOOL sources need a tool name")
        elif self.name is not None or not self.trusted:
            raise ValueError(f"{self.kind} sources carry no name and are always trusted")

    def __str__(self) -> str:
        if self.kind != "TOOL":
            return self.kind
        return f"tool:{self.name}({'trusted' if self.trusted else 'untrusted'})"

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "trusted": self.trusted}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Source:
        return cls(kind=data["kind"], name=data.get("name"), trusted=bool(data.get("trusted", True)))


USER = Source("USER")
SYSTEM = Source("SYSTEM")
PLANNER = Source("PLANNER")

Sources = frozenset[Source]
NO_SOURCES: Sources = frozenset()


def tool(name: str, trusted: bool) -> Source:
    return Source("TOOL", name, trusted)


def union(*sets: Iterable[Source]) -> Sources:
    out: set[Source] = set()
    for s in sets:
        out.update(s)
    return frozenset(out)


@dataclass(frozen=True, slots=True)
class Labeled:
    """An immutable labelled tree. ``value`` is a scalar, a tuple of Labeled or a dict of Labeled.

    ``sources`` are the node's *own* sources. Ancestors' sources are pushed down by :func:`select`, and
    :meth:`all_sources` unions the whole subtree, so a consumer of any part of the tree sees everything that
    influenced it.
    """

    value: Scalar | tuple[Labeled, ...] | dict[str, Labeled]
    sources: Sources

    def all_sources(self) -> Sources:
        acc: set[Source] = set(self.sources)
        for child in self.children():
            acc.update(child.all_sources())
        return frozenset(acc)

    def children(self) -> Sequence[Labeled]:
        if isinstance(self.value, tuple):
            return self.value
        if isinstance(self.value, dict):
            return tuple(self.value.values())
        return ()

    def is_trusted(self) -> bool:
        return all(s.trusted for s in self.all_sources())

    def untrusted_sources(self) -> Sources:
        return frozenset(s for s in self.all_sources() if not s.trusted)

    def plain(self) -> Any:
        """The underlying value with every label stripped (what a tool receives)."""
        if isinstance(self.value, tuple):
            return [c.plain() for c in self.value]
        if isinstance(self.value, dict):
            return {k: c.plain() for k, c in self.value.items()}
        return self.value

    def to_json(self) -> dict[str, Any]:
        value: Any
        if isinstance(self.value, tuple):
            value = [c.to_json() for c in self.value]
        elif isinstance(self.value, dict):
            value = {k: c.to_json() for k, c in self.value.items()}
        else:
            value = self.value
        return {"value": value, "sources": [s.to_json() for s in sorted(self.sources, key=str)]}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Labeled:
        sources = frozenset(Source.from_json(s) for s in data["sources"])
        raw = data["value"]
        if isinstance(raw, list):
            return cls(tuple(cls.from_json(c) for c in raw), sources)
        if isinstance(raw, dict):
            return cls({k: cls.from_json(c) for k, c in raw.items()}, sources)
        return cls(raw, sources)


def wrap(raw: Any, sources: Iterable[Source]) -> Labeled:
    """Label a plain JSON-like value uniformly (every node gets ``sources``)."""
    srcs = frozenset(sources)
    if isinstance(raw, Labeled):
        return raw
    if isinstance(raw, Mapping):
        return Labeled({str(k): wrap(v, srcs) for k, v in raw.items()}, srcs)
    if isinstance(raw, list | tuple):
        return Labeled(tuple(wrap(v, srcs) for v in raw), srcs)
    if raw is None or isinstance(raw, str | int | float | bool):
        return Labeled(raw, srcs)
    return Labeled(str(raw), srcs)


def scalar(value: Scalar, *sources: Source) -> Labeled:
    return Labeled(value, frozenset(sources))


_SEGMENT = re.compile(r"^([A-Za-z_][\w\-]*)?((?:\[\d+\])*)$")


def _push(child: Labeled, parent_sources: Sources) -> Labeled:
    return child if parent_sources <= child.sources else Labeled(child.value, child.sources | parent_sources)


def _get_key(node: Labeled, key: str) -> Labeled:
    if isinstance(node.value, tuple):  # map over list items
        return Labeled(tuple(_get_key(_push(item, node.sources), key) for item in node.value), node.sources)
    if isinstance(node.value, dict):
        if key not in node.value:
            raise ProvenanceError(f"no field {key!r}")
        return _push(node.value[key], node.sources)
    raise ProvenanceError(f"cannot select field {key!r} from a scalar")  # noqa: S608


def _get_index(node: Labeled, index: int) -> Labeled:
    if not isinstance(node.value, tuple):
        raise ProvenanceError(f"cannot index a non-list with [{index}]")
    if index >= len(node.value):
        raise ProvenanceError(f"index [{index}] out of range (len {len(node.value)})")
    return _push(node.value[index], node.sources)


def select(node: Labeled, path: str) -> Labeled:
    """Project ``path`` (``a.b[0].c``) out of a labelled tree, pushing ancestors' sources down.

    Applied to a list, a key segment maps over the items.
    """
    if path.strip() == "":
        return node
    current = node
    for segment in path.split("."):
        m = _SEGMENT.match(segment)
        if not m:
            raise ProvenanceError(f"bad path segment {segment!r}")
        key, indexes = m.group(1), m.group(2)
        if key:
            current = _get_key(current, key)
        for idx in re.findall(r"\[(\d+)\]", indexes):
            current = _get_index(current, int(idx))
    return current


def _compare(cmp: Cmp, left: Any, right: Any) -> bool:
    if cmp == "contains":
        return str(right).casefold() in str(left).casefold()
    if cmp == "eq":
        return bool(left == right)
    if cmp == "ne":
        return bool(left != right)
    try:
        if cmp == "lt":
            return bool(left < right)
        if cmp == "le":
            return bool(left <= right)
        if cmp == "gt":
            return bool(left > right)
        return bool(left >= right)
    except TypeError as e:
        raise ProvenanceError(f"cannot compare {left!r} {cmp} {right!r}") from e


def filter_items(node: Labeled, field: str, cmp: Cmp, value: Labeled) -> Labeled:
    """Keep list items whose ``field`` satisfies ``cmp value``.

    Selection taint (design §2.6): every kept item additionally carries the sources of the inspected field
    across all examined items, and the sources of ``value``.
    """
    if not isinstance(node.value, tuple):
        raise ProvenanceError("filter needs a list")
    items = [_push(item, node.sources) for item in node.value]
    inspected = [select(item, field) for item in items]
    taint = union(*(f.all_sources() for f in inspected), value.all_sources())
    kept = tuple(
        Labeled(item.value, item.sources | taint)
        for item, f in zip(items, inspected, strict=True)
        if _compare(cmp, f.plain(), value.plain())
    )
    return Labeled(kept, node.sources)


def _number(x: Labeled, what: str) -> int | float:
    v = x.value
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise ProvenanceError(f"compute operand {what} must be a number, got {type(v).__name__}")
    return v


def compute(fn: Fn, a: Labeled, b: Labeled) -> Labeled:
    """Arithmetic on two labelled numbers; the result carries both operands' sources."""
    x, y = _number(a, "a"), _number(b, "b")
    if fn == "add":
        r: int | float = x + y
    elif fn == "sub":
        r = x - y
    elif fn == "mul":
        r = x * y
    else:
        if y == 0:
            raise ProvenanceError("division by zero")
        r = x / y
    if isinstance(r, float) and not math.isfinite(r):
        raise ProvenanceError("non-finite result")
    return Labeled(r, a.all_sources() | b.all_sources())


def reduce_items(node: Labeled, fn: ReduceFn) -> Labeled:
    """Aggregate a labelled list into one number; the result carries every item's sources (design §1)."""
    if not isinstance(node.value, tuple):
        raise ProvenanceError("reduce needs a list")
    items = [_push(item, node.sources) for item in node.value]
    sources = union(node.sources, *(i.all_sources() for i in items))
    if fn == "count":
        return Labeled(len(items), sources)
    try:
        numbers = [_number(i, f"item {k}") for k, i in enumerate(items)]
    except ProvenanceError as e:
        raise ProvenanceError(f"reduce {fn} needs a list of numbers (give reduce a numeric path): {e}") from e
    if fn == "sum":
        return Labeled(sum(numbers), sources)
    if not numbers:
        raise ProvenanceError(f"{fn} of an empty list")
    return Labeled(min(numbers) if fn == "min" else max(numbers), sources)


def extracted(raw: Any, inputs: Sequence[Labeled], instruction: Labeled) -> Labeled:
    """Label an extractor's output with everything the extractor was shown (design §2.5)."""
    return wrap(raw, union(*(i.all_sources() for i in inputs), instruction.all_sources()))


_NUM_TOKEN = re.compile(r"-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?")


def ground_literal(value: Scalar, prompt: str) -> Source:
    """USER if the literal occurs verbatim in the prompt (design §2.1), else PLANNER."""
    if isinstance(value, str):
        needle = " ".join(value.split()).casefold()
        haystack = " ".join(prompt.split()).casefold()
        return USER if needle and needle in haystack else PLANNER
    if isinstance(value, bool) or value is None:
        return PLANNER
    for token in _NUM_TOKEN.findall(prompt):
        try:
            if float(token.replace(",", "")) == float(value):
                return USER
        except ValueError:  # pragma: no cover - regex guarantees a float-parsable token
            continue
    return PLANNER
