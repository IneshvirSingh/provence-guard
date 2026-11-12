"""Property tests for the policy engine and the runner: C1 (no untrusted auto-allow), totality, precedence."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from provguard.core.plan import Plan, ToolSpec
from provguard.core.policy import ArgPolicy, Constraints, PolicySet, ToolPolicy, decide, entry_matches
from provguard.core.provenance import Labeled, Source, select
from provguard.core.runner import PlanRunner, confirm_permissive, confirm_strict
from provguard.core.trust import ToolTrust, TrustConfig
from tests.property.strategies import TOOL_NAMES, labeled_trees, scalars, source_sets, sources

allow_entries = st.lists(
    st.sampled_from(["USER", "SYSTEM", "PLANNER", *(f"tool:{t}" for t in TOOL_NAMES)]),
    max_size=5,
    unique=True,
)
verdicts = st.sampled_from(["CONFIRM", "DENY"])
constraints = st.one_of(
    st.none(),
    st.builds(
        Constraints,
        pattern=st.one_of(st.none(), st.just("^[A-Z]{2}")),
        minimum=st.one_of(st.none(), st.floats(-10, 10)),
        maximum=st.one_of(st.none(), st.floats(-10, 10)),
        exclusive=st.booleans(),
    ),
)
arg_policies = st.builds(
    ArgPolicy, allow=allow_entries, else_=verdicts, constraints=constraints, on_violation=verdicts
)
arg_names = st.sampled_from(["a", "b", "c", "d"])
tool_policies = st.builds(
    ToolPolicy,
    guarded=st.booleans(),
    default=st.one_of(st.none(), arg_policies),
    args=st.dictionaries(arg_names, arg_policies, max_size=4),
)
policy_sets = st.builds(
    PolicySet,
    version=st.integers(0, 9),
    unlisted_tool=verdicts,
    tools=st.dictionaries(st.sampled_from(["t1", "t2"]), tool_policies, max_size=2),
)
args = st.dictionaries(arg_names, labeled_trees(3), max_size=3)


@given(allow_entries, sources)
def test_no_entry_matches_an_untrusted_source(entries, s):
    if not s.trusted:
        assert not any(entry_matches(e, s) for e in entries)


@settings(max_examples=200, deadline=None)
@given(policy_sets, st.sampled_from(["t1", "t2", "t3"]), args)
def test_c1_allow_implies_every_source_allowed_and_trusted(ps, tool_name, a):
    d = decide(ps, tool_name, a)  # total: never raises
    assert d.verdict in {"ALLOW", "CONFIRM", "DENY"} and d.policy_version == ps.version
    assert decide(ps, tool_name, a) == d  # deterministic
    tp = ps.tools.get(tool_name)
    if tp is None:
        assert d.verdict == ps.unlisted_tool
        return
    if not tp.guarded:
        assert d.verdict == "ALLOW"
        return
    outcomes = {r.outcome for r in d.reasons}
    assert d.verdict == ("DENY" if "DENY" in outcomes else "CONFIRM" if "CONFIRM" in outcomes else "ALLOW")
    if d.verdict == "ALLOW":
        for name, value in a.items():
            rule = tp.args.get(name, tp.default) or ArgPolicy(allow=["USER"])
            for s in value.all_sources():
                assert s.trusted and any(entry_matches(e, s) for e in rule.allow)
    else:
        assert any(r.outcome == d.verdict for r in d.reasons)


# ---- runner-level C1: random linear plans over a random trust config --------------------------------

READ_TOOLS = {t: ToolSpec(name=t, args={}) for t in TOOL_NAMES}
GUARDED = ToolSpec(name="act", args={"a": True, "b": False})
TOOLS = {**READ_TOOLS, "act": GUARDED}
FIELDS = ["amount", "subject", "id"]


@st.composite
def runs(draw: st.DrawFn):
    trust = TrustConfig(
        version=1,
        tools={
            t: ToolTrust(
                trusted=draw(st.booleans()),
                fields={
                    f: draw(st.sampled_from(["trusted", "untrusted"])) for f in FIELDS if draw(st.booleans())
                },
            )
            for t in TOOL_NAMES
        },
    )
    policy = PolicySet(
        version=1,
        tools={
            **{t: ToolPolicy(guarded=False) for t in TOOL_NAMES},
            "act": ToolPolicy(guarded=True, default=draw(arg_policies), args={"a": draw(arg_policies)}),
        },
    )
    data = {
        t: [{f: draw(scalars) for f in FIELDS} for _ in range(draw(st.integers(1, 3)))] for t in TOOL_NAMES
    }
    steps: list[dict] = []
    names: list[str] = []
    for i, t in enumerate(draw(st.lists(st.sampled_from(TOOL_NAMES), min_size=1, max_size=3))):
        steps.append({"op": "call", "out": f"r{i}", "tool": t, "args": {}})
        names.append(f"r{i}")
    ref = draw(st.sampled_from(names))
    field = draw(st.sampled_from(FIELDS))
    kind = draw(st.sampled_from(["select", "filter", "extract", "compute"]))
    if kind == "select":
        steps.append({"op": "select", "out": "v", "ref": ref, "path": f"[0].{field}"})
    elif kind == "filter":
        steps.append(
            {"op": "filter", "out": "f", "ref": ref, "field": field, "cmp": "ne", "value": {"lit": "zzz"}}
        )
        steps.append({"op": "select", "out": "v", "ref": "f", "path": f"[0].{field}"})
    elif kind == "compute":
        steps.append(
            {
                "op": "compute",
                "out": "v",
                "fn": "add",
                "a": {"ref": ref, "path": f"[0].{field}"},
                "b": {"lit": 1},
            }
        )
    else:
        steps.append(
            {
                "op": "extract",
                "out": "e",
                "from": [{"ref": ref}],
                "instruction": "x",
                "schema": {"v": {"type": "str"}},
            }
        )
        steps.append({"op": "select", "out": "v", "ref": "e", "path": "v"})
    steps.append(
        {"op": "call", "out": "out", "tool": "act", "args": {"a": {"ref": "v"}, "b": {"lit": draw(scalars)}}}
    )
    return trust, policy, data, Plan.model_validate({"steps": steps}), draw(st.booleans())


@settings(max_examples=300, deadline=None)
@given(runs())
def test_c1_end_to_end_untrusted_data_never_reaches_a_guarded_call_unconfirmed(run):
    trust, policy, data, plan, permissive = run
    executed: list[tuple[str, dict]] = []

    def call_tool(name: str, a: dict) -> object:
        executed.append((name, a))
        return data.get(name, {"message": "ok"})

    runner = PlanRunner(
        trust=trust,
        policy=policy,
        tools=TOOLS,
        call_tool=call_tool,
        extractor=lambda inputs, instr, schema: {"v": "extracted"},
        confirm=confirm_permissive if permissive else confirm_strict,
        prompt="",
    )
    res = runner.run(plan)
    acts = [r for r in res.records if r.tool == "act"]
    assert len(acts) <= 1
    for rec in acts:
        assert rec.decision is not None  # complete mediation
        if rec.executed:
            assert rec.decision.verdict != "DENY"
            if rec.decision.verdict == "ALLOW":
                for reason in rec.decision.reasons:
                    assert all("untrusted" not in s for s in reason.sources)
                assert rec.confirmed is None
            else:
                assert permissive and rec.confirmed is True
        else:
            assert res.status in {"denied", "error"}
    if res.status == "ok":
        assert executed[-1][0] == "act"
    # every executed tool call happened after its own decision, never before
    assert [name for name, _ in executed].count("act") == sum(1 for r in acts if r.executed)


@given(labeled_trees(), st.text(max_size=5))
def test_select_on_random_path_never_raises_anything_but_provenance_error(node, path):
    from provguard.core.provenance import ProvenanceError

    try:
        out = select(node, path)
    except ProvenanceError:
        return
    assert isinstance(out, Labeled) and out.all_sources() <= node.all_sources()


@given(source_sets)
def test_sources_serialise(srcs: frozenset[Source]):
    assert {Source.from_json(s.to_json()) for s in srcs} == set(srcs)
