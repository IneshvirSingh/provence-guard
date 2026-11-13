import pytest

from provguard.core import USER, Labeled, Plan, PlanError, ToolSpec, tool
from provguard.core.provenance import ProvenanceError, reduce_items, wrap

T = tool("ledger", trusted=True)
U = tool("notes", trusted=False)


def test_reduce_sum_count_min_max_and_sources():
    lst = Labeled((Labeled(1.5, frozenset({T})), Labeled(2, frozenset({U}))), frozenset({T}))
    assert reduce_items(lst, "sum").value == 3.5
    assert reduce_items(lst, "count").value == 2
    assert reduce_items(lst, "min").value == 1.5
    assert reduce_items(lst, "max").value == 2
    assert reduce_items(lst, "sum").sources == frozenset({T, U})  # every item was examined
    assert not reduce_items(lst, "sum").is_trusted()


def test_reduce_edge_cases():
    empty = wrap([], frozenset({USER}))
    assert reduce_items(empty, "sum").value == 0 and reduce_items(empty, "count").value == 0
    with pytest.raises(ProvenanceError, match="empty"):
        reduce_items(empty, "max")
    with pytest.raises(ProvenanceError, match="needs a list"):
        reduce_items(wrap(3, frozenset()), "sum")
    with pytest.raises(ProvenanceError, match="number"):
        reduce_items(wrap(["a"], frozenset()), "sum")


def test_reduce_in_plan_validates_scope():
    tools = {"t": ToolSpec(name="t")}
    ok = Plan.model_validate(
        {
            "steps": [
                {"op": "call", "out": "x", "tool": "t"},
                {"op": "select", "out": "a", "ref": "x", "path": "amount"},
                {"op": "reduce", "out": "s", "ref": "a", "fn": "sum"},
                {"op": "respond", "template": "{s}"},
            ]
        }
    )
    ok.validate_against(tools)
    bad = Plan.model_validate({"steps": [{"op": "reduce", "out": "s", "ref": "nope", "fn": "sum"}]})
    with pytest.raises(PlanError, match="not defined"):
        bad.validate_against(tools)


def test_reduce_with_path_selects_the_field_first():
    from provguard.core import PolicySet, TrustConfig
    from provguard.core.runner import PlanRunner

    records = [{"amount": 2.5, "subject": "a"}, {"amount": 3, "subject": "b"}]
    plan = Plan.model_validate(
        {
            "steps": [
                {"op": "call", "out": "tx", "tool": "ledger"},
                {"op": "reduce", "out": "total", "ref": "tx", "path": "amount", "fn": "sum"},
                {"op": "reduce", "out": "bad", "ref": "tx", "fn": "sum"},
            ]
        }
    )
    runner = PlanRunner(
        trust=TrustConfig(version=1, default="untrusted", tools={}),
        policy=PolicySet.model_validate({"version": 1, "tools": {"ledger": {"guarded": False}}}),
        tools={"ledger": ToolSpec(name="ledger")},
        call_tool=lambda name, args: records,
        extractor=lambda *a: None,
    )
    res = runner.run(plan)
    assert res.status == "error" and "numeric path" in (res.records[-1].error or "")
    assert res.records[1].executed  # the path form worked before the bad step


def test_respond_template_with_attribute_access_fails_closed():
    from provguard.core import PolicySet, TrustConfig
    from provguard.core.runner import PlanRunner

    plan = Plan.model_validate(
        {"steps": [{"op": "call", "out": "tx", "tool": "ledger"}, {"op": "respond", "template": "{tx.id}"}]}
    )
    res = PlanRunner(
        trust=TrustConfig(version=1, default="untrusted", tools={}),
        policy=PolicySet.model_validate({"version": 1, "tools": {"ledger": {"guarded": False}}}),
        tools={"ledger": ToolSpec(name="ledger")},
        call_tool=lambda name, args: [{"id": 1}],
        extractor=lambda *a: None,
    ).run(plan)
    assert res.status == "error" and "bad respond template" in res.records[-1].error
