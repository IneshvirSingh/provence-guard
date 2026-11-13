"""Extractor (Q-LLM): reads untrusted text, returns JSON fields. Has no tools and no memory (design §2.5)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from provguard.agent.prompts import extractor_messages
from provguard.core.plan import FieldSpec
from provguard.llm.client import LLMClient

JSON_OBJECT = {"type": "json_object"}
MAX_DOC_CHARS = 20_000


def render_schema(schema: Mapping[str, FieldSpec]) -> str:
    return json.dumps({k: v.model_dump(exclude_none=True) for k, v in schema.items()}, indent=1)


def render_document(doc: Any) -> str:
    text = doc if isinstance(doc, str) else json.dumps(doc, default=str, indent=1)
    return text[:MAX_DOC_CHARS]


class LLMExtractor:
    """Callable matching :data:`provguard.core.runner.ExtractorCallable`."""

    def __init__(self, client: LLMClient, *, temperature: float = 0.0) -> None:
        self.client = client
        self.temperature = temperature

    def __call__(self, inputs: list[Any], instruction: str, schema: Mapping[str, FieldSpec]) -> Any:
        messages = extractor_messages(
            [render_document(d) for d in inputs], instruction, render_schema(schema)
        )
        result = self.client.chat(messages, temperature=self.temperature, response_format=JSON_OBJECT)
        try:
            return json.loads(str(result.message.get("content") or ""))
        except json.JSONDecodeError:
            return None  # the runner validates and retries once, then fails closed


__all__ = ["LLMExtractor", "render_document", "render_schema"]
