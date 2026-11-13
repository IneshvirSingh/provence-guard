"""Validation of quarantined-extractor output against an Extract schema. Design §2.5."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from provguard.core.plan import FieldSpec
from provguard.core.provenance import Scalar


class ExtractionError(ValueError):
    """Extractor output does not conform to the schema (fail closed after the agent's single retry)."""


def validate_extraction(schema: Mapping[str, FieldSpec], raw: Any) -> dict[str, Scalar]:
    if not isinstance(raw, Mapping):
        raise ExtractionError("extraction must be a JSON object")
    extra = set(raw) - set(schema)
    if extra:
        raise ExtractionError(f"unexpected fields: {sorted(extra)}")
    out: dict[str, Scalar] = {}
    for name, spec in schema.items():
        if spec.optional and raw.get(name) is None:
            out[name] = None
            continue
        if name not in raw:
            raise ExtractionError(f"missing field {name!r}")
        out[name] = _check(name, spec, raw[name])
    return out


def _check(name: str, spec: FieldSpec, value: Any) -> Scalar:
    if spec.type == "bool":
        if not isinstance(value, bool):
            raise ExtractionError(f"{name}: expected bool")
        return value
    if spec.type == "str":
        if not isinstance(value, str):
            raise ExtractionError(f"{name}: expected str")
        if spec.pattern is not None and re.search(spec.pattern, value) is None:
            raise ExtractionError(f"{name}: {value!r} does not match {spec.pattern!r}")
        if spec.enum is not None and value not in spec.enum:
            raise ExtractionError(f"{name}: {value!r} not in enum")
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExtractionError(f"{name}: expected {spec.type}")
    if spec.type == "int" and not float(value).is_integer():
        raise ExtractionError(f"{name}: expected int")
    number: int | float = int(value) if spec.type == "int" else float(value)
    if spec.minimum is not None and number < spec.minimum:
        raise ExtractionError(f"{name}: {number} < minimum {spec.minimum}")
    if spec.maximum is not None and number > spec.maximum:
        raise ExtractionError(f"{name}: {number} > maximum {spec.maximum}")
    if spec.enum is not None and number not in spec.enum:
        raise ExtractionError(f"{name}: {number} not in enum")
    return number
