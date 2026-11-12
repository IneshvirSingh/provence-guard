"""Our LLM element inside a real AgentDojo pipeline on the banking suite, with a scripted transport."""

import json
from pathlib import Path

from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.types import (
    ChatAssistantMessage,
    ChatSystemMessage,
    ChatToolResultMessage,
    ChatUserMessage,
    text_content_block_from_string,
)

from provguard.bench.attacks import prose_model_name
from provguard.bench.llm_element import from_openai_message, to_openai_messages, to_openai_tools
from provguard.bench.pipelines import DEFENSES, build_pipeline
from provguard.llm.client import LLMClient
from provguard.llm.providers import Limits, ModelRef

REF = ModelRef(
    provider="groq", model="llama-3.3-70b-versatile", base_url="https://x", api_key_env="X", limits=Limits()
)


def resp(text=None, calls=None):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(calls)
        ]
    return {
        "choices": [{"message": msg}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class Scripted:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, payload):
        self.calls.append(payload)
        return self.responses.pop(0) if self.responses else resp("done")


def test_message_conversion_has_no_name_field_and_uses_system_role():
    msgs = [
        ChatSystemMessage(role="system", content=[text_content_block_from_string("sys")]),
        ChatUserMessage(role="user", content=[text_content_block_from_string("hi")]),
        ChatAssistantMessage(
            role="assistant",
            content=None,
            tool_calls=[FunctionCall(function="get_balance", args={}, id="c1")],
        ),
        ChatToolResultMessage(
            role="tool",
            content=[text_content_block_from_string("12.0")],
            tool_call=FunctionCall(function="get_balance", args={}),
            tool_call_id="c1",
            error=None,
        ),
        ChatToolResultMessage(
            role="tool",
            content=[text_content_block_from_string("")],
            tool_call=FunctionCall(function="x", args={}),
            tool_call_id=None,
            error="ValidationError: bad",
        ),
    ]
    out = to_openai_messages(msgs)
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["tool_calls"][0]["function"] == {"name": "get_balance", "arguments": "{}"}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "12.0"}
    assert out[4]["content"].startswith("ValidationError") and all("name" not in m for m in out)


def test_from_openai_message_tolerates_bad_json():
    m = from_openai_message(
        {
            "content": "x",
            "tool_calls": [
                {"id": "c", "function": {"name": "f", "arguments": "{not json"}},
                {"id": "d", "function": {"name": "g", "arguments": "[1]"}},
            ],
        }
    )
    assert (
        m["tool_calls"][0].args == {} and m["tool_calls"][1].args == {} and m["content"][0]["content"] == "x"
    )
    assert from_openai_message({"content": None})["content"] is None


def test_tools_schema_from_banking_suite():
    suite = get_suite("v1.2.2", "banking")
    tools = to_openai_tools(suite.tools)
    names = {t["function"]["name"] for t in tools}
    assert "send_money" in names and tools[0]["type"] == "function"
    sm = next(t for t in tools if t["function"]["name"] == "send_money")
    assert set(sm["function"]["parameters"]["properties"]) == {"recipient", "amount", "subject", "date"}


def test_banking_user_task_1_runs_end_to_end_with_scripted_model():
    suite = get_suite("v1.2.2", "banking")
    task = suite.get_user_task_by_id("user_task_1")
    transport = Scripted(
        [
            resp(calls=[("get_most_recent_transactions", {"n": 100})]),
            resp("Your total spending in March 2022 was 1050."),
        ]
    )
    client = LLMClient(REF, transport=transport)
    pipeline = build_pipeline(client, "none")
    utility, security = suite.run_task_with_pipeline(pipeline, task, injection_task=None, injections={})
    assert utility is True and security is True
    assert len(transport.calls) == 2
    assert (
        transport.calls[1]["messages"][-1]["role"] == "tool"
        and "Pizza party" in transport.calls[1]["messages"][-1]["content"]
    )
    assert pipeline.name == "baseline-groq_llama-3.3-70b-versatile-none"
    assert client.summary.requests == 2


def test_all_prompt_defenses_build_and_tool_filter_prunes():
    for d in DEFENSES:
        if d == "transformers_pi_detector":
            continue
        assert build_pipeline(LLMClient(REF, transport=Scripted([])), d).name.endswith(d)
    suite = get_suite("v1.2.2", "banking")
    task = suite.get_user_task_by_id("user_task_1")
    transport = Scripted(
        [
            resp("get_most_recent_transactions"),  # tool filter answer
            resp(calls=[("get_most_recent_transactions", {"n": 100})]),
            resp("1050"),
        ]
    )
    pipeline = build_pipeline(LLMClient(REF, transport=transport), "tool_filter")
    utility, _ = suite.run_task_with_pipeline(pipeline, task, injection_task=None, injections={})
    assert utility and transport.calls[0]["tool_choice"] == "none"
    assert [t["function"]["name"] for t in transport.calls[1]["tools"]] == ["get_most_recent_transactions"]
    spot = build_pipeline(
        LLMClient(REF, transport=Scripted([resp(calls=[("get_balance", {})]), resp("ok")])),
        "spotlighting_with_delimiting",
    )
    rt = FunctionsRuntime(suite.tools)
    env = suite.load_and_inject_default_environment({})
    *_, messages, _ = spot.query("balance?", rt, env)
    assert messages[-2]["content"][0]["content"].startswith("<<")


def test_prose_model_name():
    assert prose_model_name("baseline-groq_llama-3.3-70b-versatile-none") == "Llama"
    assert prose_model_name("x-openai_gpt-oss-120b") == "GPT"
    assert prose_model_name("gemini-2.5") == "AI model developed by Google"
    assert prose_model_name(None) == "the AI language model"


def test_repo_policy_files_exist():
    assert (Path("policies") / "banking.yaml").exists()
