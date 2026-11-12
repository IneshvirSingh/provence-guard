import pytest
from pydantic import ValidationError

from provguard.core.plan import MAX_STEPS, Plan, PlanError, ToolSpec

TOOLS = {
    "read_file": ToolSpec(name="read_file", args={"file_path": True}),
    "get_most_recent_transactions": ToolSpec(name="get_most_recent_transactions", args={"n": False}),
    "send_money": ToolSpec(
        name="send_money", args={"recipient": True, "amount": True, "subject": True, "date": True}
    ),
}


def plan(*steps):
    return Plan.model_validate({"steps": list(steps)})


REFUND = [
    {"op": "call", "out": "tx", "tool": "get_most_recent_transactions", "args": {"n": {"lit": 100}}},
    {"op": "filter", "out": "f", "ref": "tx", "field": "sender", "cmp": "eq", "value": {"lit": "GB29"}},
    {
        "op": "compute",
        "out": "diff",
        "fn": "sub",
        "a": {"ref": "f", "path": "[0].amount"},
        "b": {"lit": 12.0},
    },
    {
        "op": "call",
        "out": "r",
        "tool": "send_money",
        "args": {
            "recipient": {"lit": "GB29"},
            "amount": {"ref": "diff"},
            "subject": {"lit": "Refund"},
            "date": {"lit": "2022-04-01"},
        },
    },
    {"op": "respond", "template": "Sent {diff}."},
]


def test_valid_plan_parses_and_validates():
    p = plan(*REFUND)
    p.validate_against(TOOLS)
    assert [s.op for s in p.steps] == ["call", "filter", "compute", "call", "respond"]
    assert Plan.model_validate_json(p.model_dump_json(by_alias=True)) == p


def test_extract_and_foreach_parse():
    p = plan(
        {"op": "call", "out": "f", "tool": "read_file", "args": {"file_path": {"lit": "bill.txt"}}},
        {
            "op": "extract",
            "out": "bill",
            "from": [{"ref": "f"}],
            "instruction": "find the iban",
            "schema": {"iban": {"type": "str"}},
        },
        {
            "op": "foreach",
            "out": "amts",
            "ref": "bill",
            "max_items": 3,
            "steps": [{"op": "select", "out": "a", "ref": "item", "path": "iban"}],
        },
    )
    p.validate_against(TOOLS)
    assert p.steps[1].from_[0].ref == "f" and p.steps[1].schema_["iban"].type == "str"


@pytest.mark.parametrize(
    ("steps", "msg"),
    [
        ([{"op": "call", "out": "x", "tool": "nope", "args": {}}], "unknown tool"),
        ([{"op": "call", "out": "x", "tool": "read_file", "args": {}}], "requires argument"),
        (
            [
                {
                    "op": "call",
                    "out": "x",
                    "tool": "read_file",
                    "args": {"file_path": {"lit": "a"}, "zz": {"lit": 1}},
                }
            ],
            "no argument",
        ),
        ([{"op": "select", "out": "x", "ref": "missing", "path": "a"}], "not defined"),
        (
            [
                {"op": "call", "out": "x", "tool": "get_most_recent_transactions", "args": {}},
                {"op": "select", "out": "x", "ref": "x", "path": "a"},
            ],
            "already defined",
        ),
        (
            [{"op": "call", "out": "item", "tool": "get_most_recent_transactions", "args": {}}],
            "already defined",
        ),
        (
            [{"op": "filter", "out": "x", "ref": "nope", "field": "a", "cmp": "eq", "value": {"lit": 1}}],
            "not defined",
        ),
        ([{"op": "compute", "out": "x", "fn": "add", "a": {"ref": "nope"}, "b": {"lit": 1}}], "not defined"),
        (
            [
                {
                    "op": "extract",
                    "out": "x",
                    "from": [{"ref": "nope"}],
                    "instruction": "i",
                    "schema": {"a": {"type": "str"}},
                }
            ],
            "not defined",
        ),
        (
            [
                {"op": "call", "out": "t", "tool": "get_most_recent_transactions", "args": {}},
                {
                    "op": "foreach",
                    "out": "o",
                    "ref": "t",
                    "max_items": 2,
                    "steps": [
                        {"op": "call", "out": "y", "tool": "read_file", "args": {"file_path": {"ref": "zz"}}}
                    ],
                },
            ],
            "not defined",
        ),
    ],
)
def test_static_validation_errors(steps, msg):
    with pytest.raises(PlanError, match=msg):
        plan(*steps).validate_against(TOOLS)


def test_schema_level_errors():
    with pytest.raises(ValidationError):  # respond not last
        plan({"op": "respond", "template": "x"}, {"op": "call", "out": "a", "tool": "read_file", "args": {}})
    with pytest.raises(ValidationError):  # nested foreach rejected by the schema (BodyStep has no foreach)
        plan(
            {
                "op": "foreach",
                "out": "o",
                "ref": "t",
                "max_items": 2,
                "steps": [
                    {
                        "op": "foreach",
                        "out": "p",
                        "ref": "item",
                        "max_items": 2,
                        "steps": [{"op": "select", "out": "s", "ref": "item", "path": "a"}],
                    }
                ],
            },
        )
    with pytest.raises(ValidationError):  # too many steps
        plan(
            *([{"op": "call", "out": f"o{i}", "tool": "read_file", "args": {}} for i in range(MAX_STEPS + 1)])
        )
    with pytest.raises(ValidationError):  # max_items bound
        plan(
            {
                "op": "foreach",
                "out": "o",
                "ref": "t",
                "max_items": 99,
                "steps": [{"op": "select", "out": "s", "ref": "item", "path": "a"}],
            }
        )
    with pytest.raises(ValidationError):  # unknown op / extra field
        plan({"op": "jump", "out": "o"})
