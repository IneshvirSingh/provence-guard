import pytest

from provguard.agent import LLMExtractor, Planner, PlannerError, parse_plan, render_tools
from provguard.core import PlanError, ToolSpec
from provguard.core.plan import FieldSpec

from .conftest import Scripted

TOOLS = {
    "get_note": ToolSpec(name="get_note", args={"title": True}, description="Read a note [title: string]"),
    "count": ToolSpec(name="count", args={}),
}
GOOD = {
    "steps": [
        {"op": "call", "out": "n", "tool": "get_note", "args": {"title": {"lit": "offsite"}}},
        {"op": "respond", "template": "{n}"},
    ]
}


def test_parse_plan_accepts_fenced_and_bare_list():
    fenced = '```json\n{"steps": [{"op":"respond","template":"hi"}]}\n```'
    assert len(parse_plan(fenced, TOOLS).steps) == 1
    assert len(parse_plan('[{"op":"respond","template":"hi"}]', TOOLS).steps) == 1


@pytest.mark.parametrize(
    ("text", "msg"),
    [
        ("not json", "not JSON"),
        ('{"steps": [{"op": "fly"}]}', "schema"),
        ('{"steps": [{"op": "call", "out": "x", "tool": "nope"}]}', "unknown tool"),
    ],
)
def test_parse_plan_rejects(text, msg):
    with pytest.raises(PlanError, match=msg):
        parse_plan(text, TOOLS)


def test_render_tools_marks_optional_args():
    assert (
        render_tools({"t": ToolSpec(name="t", args={"a": True, "b": False}, description="d")})
        == "- t(a, b?): d"
    )


def test_planner_retries_once_with_the_error_then_succeeds(make_client):
    transport = Scripted(plans=['{"steps": [{"op": "call", "out": "x", "tool": "nope"}]}', GOOD])
    res = Planner(make_client(transport)).plan("read offsite", TOOLS)
    assert res.attempts == 2 and res.plan.steps[0].op == "call"
    second = transport.payloads[1]["messages"]
    assert second[-1]["role"] == "user" and "unknown tool" in second[-1]["content"]
    assert transport.payloads[0]["response_format"] == {"type": "json_object"}
    assert "get_note(title)" in transport.payloads[0]["messages"][0]["content"]


def test_planner_fails_closed(make_client):
    transport = Scripted(plans=["x", "y"])
    with pytest.raises(PlannerError, match="2 attempts"):
        Planner(make_client(transport)).plan("hi", TOOLS)


def test_extractor_delimits_documents_and_returns_json(make_client):
    transport = Scripted(extractions=[{"iban": "DE1", "total": 12.5}, "garbage"])
    ex = LLMExtractor(make_client(transport))
    schema = {"iban": FieldSpec(type="str"), "total": FieldSpec(type="float", minimum=0)}
    out = ex(["Pay DE1 12.5 now", {"k": "v"}], "find the bill", schema)
    assert out == {"iban": "DE1", "total": 12.5}
    user = transport.payloads[0]["messages"][1]["content"]
    assert "<document index=0>\nPay DE1 12.5 now\n</document>" in user and '"k": "v"' in user
    assert '"minimum": 0' in transport.payloads[0]["messages"][0]["content"]
    assert transport.payloads[0].get("tools") is None
    assert ex([], "x", schema) is None  # bad JSON -> None; the runner validates and fails closed


class Boom(Exception):
    status_code = 400


def test_provider_json_failure_counts_as_a_failed_attempt(make_client):
    calls = {"n": 0}

    def transport(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Boom("Failed to generate JSON")
        from .conftest import reply

        return reply(GOOD)

    res = Planner(make_client(transport)).plan("read offsite", TOOLS)
    assert res.attempts == 2

    def always(payload):
        raise Boom("Failed to generate JSON")

    with pytest.raises(PlannerError, match="could not generate"):
        Planner(make_client(always)).plan("x", TOOLS)
    assert LLMExtractor(make_client(always))(["d"], "i", {"a": FieldSpec(type="str")}) is None

    def other(payload):
        raise RuntimeError("network")

    with pytest.raises(RuntimeError):
        Planner(make_client(other)).plan("x", TOOLS)
