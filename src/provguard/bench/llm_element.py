"""AgentDojo pipeline elements backed by :class:`provguard.llm.LLMClient`.

Why not AgentDojo's own ``OpenAILLM``: it sends the system prompt as ``role="developer"`` and sets
``messages[].name`` on tool results, which Groq rejects with HTTP 400 (console.groq.com/docs/openai), and it
bypasses our quota guard and cache. Message conversion mirrors ``agentdojo/agent_pipeline/llms/openai_llm.py``
(verified against agentdojo==0.1.35).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.functions_runtime import EmptyEnv, Env, Function, FunctionCall, FunctionsRuntime
from agentdojo.types import (
    ChatAssistantMessage,
    ChatMessage,
    ChatUserMessage,
    get_text_content_as_str,
    text_content_block_from_string,
)

from provguard.llm.client import LLMClient


def _text(message: ChatMessage) -> str | None:
    content = message.get("content")
    if content is None:
        return None
    return str(get_text_content_as_str(list(content)))


def to_openai_messages(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role in ("system", "user"):
            out.append({"role": role, "content": _text(m) or ""})
        elif role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": _text(m)}
            calls = m.get("tool_calls") or []
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id or f"call_{i}",
                        "type": "function",
                        "function": {"name": c.function, "arguments": json.dumps(c.args)},
                    }
                    for i, c in enumerate(calls)
                ]
            out.append(entry)
        else:  # tool result; no `name` field (Groq rejects it)
            error = m.get("error")
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id") or "call_0",
                    "content": error if error else (_text(m) or ""),
                }
            )
    return out


def to_openai_tools(functions: Sequence[Function]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": f.name,
                "description": f.description,
                "parameters": f.parameters.model_json_schema(),
            },
        }
        for f in functions
    ]


def from_openai_message(message: dict[str, Any]) -> ChatAssistantMessage:
    content = message.get("content")
    tool_calls: list[FunctionCall] | None = None
    raw_calls = message.get("tool_calls") or []
    if raw_calls:
        tool_calls = []
        for c in raw_calls:
            fn = c.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            tool_calls.append(FunctionCall(function=str(fn.get("name", "")), args=args, id=c.get("id")))
    return ChatAssistantMessage(
        role="assistant",
        content=[text_content_block_from_string(content)] if content is not None else None,
        tool_calls=tool_calls,
    )


class ProvguardLLM(BasePipelineElement):
    """Drop-in LLM element: quota-guarded, cached, provider-agnostic."""

    def __init__(self, client: LLMClient, temperature: float = 0.0, seed: int = 0) -> None:
        self.client = client
        self.temperature = temperature
        self.seed = seed
        self.name = client.model.id

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),  # noqa: B008 - AgentDojo's signature
        messages: Sequence[ChatMessage] = [],
        extra_args: dict[str, Any] = {},  # noqa: B006 - AgentDojo's signature
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict[str, Any]]:
        result = self.client.chat(
            to_openai_messages(messages),
            to_openai_tools(list(runtime.functions.values())),
            temperature=self.temperature,
            seed=self.seed,
        )
        return query, runtime, env, [*messages, from_openai_message(result.message)], extra_args


class ToolFilter(BasePipelineElement):
    """Re-implementation of AgentDojo's ``OpenAILLMToolFilter`` on our client (same prompt and mechanism)."""

    def __init__(self, client: LLMClient, prompt: str) -> None:
        self.client = client
        self.prompt = prompt

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),  # noqa: B008
        messages: Sequence[ChatMessage] = [],
        extra_args: dict[str, Any] = {},  # noqa: B006
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict[str, Any]]:
        messages = [
            *messages,
            ChatUserMessage(role="user", content=[text_content_block_from_string(self.prompt)]),
        ]
        result = self.client.chat(
            to_openai_messages(messages),
            to_openai_tools(list(runtime.functions.values())),
            tool_choice="none",
        )
        output = from_openai_message(result.message)
        text = _text(output) or ""
        runtime.update_functions({name: fn for name, fn in runtime.functions.items() if name in text})
        return query, runtime, env, [*messages, output], extra_args
