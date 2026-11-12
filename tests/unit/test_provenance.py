import json

import pytest

from provguard.core.provenance import (
    PLANNER,
    SYSTEM,
    USER,
    Labeled,
    ProvenanceError,
    Source,
    compute,
    extracted,
    filter_items,
    ground_literal,
    scalar,
    select,
    tool,
    union,
    wrap,
)

RF = tool("read_file", False)
TX = tool("get_most_recent_transactions", True)


def test_source_validation_and_str():
    assert str(USER) == "USER" and str(RF) == "tool:read_file(untrusted)"
    with pytest.raises(ValueError):
        Source("TOOL")
    with pytest.raises(ValueError):
        Source("USER", trusted=False)
    assert Source.from_json(RF.to_json()) == RF


def test_union_laws_small():
    a, b = frozenset({USER}), frozenset({RF})
    assert union(a, b) == union(b, a) == frozenset({USER, RF})
    assert union(a, a) == a and union() == frozenset()


def test_wrap_plain_and_json_roundtrip():
    raw = {"id": 1, "items": [{"amount": 2.5, "memo": "x"}, None], "ok": True}
    node = wrap(raw, {TX})
    assert node.plain() == raw
    assert node.all_sources() == {TX}
    again = Labeled.from_json(json.loads(json.dumps(node.to_json())))
    assert again == node
    assert wrap(node, {USER}) is node
    assert wrap(object(), {USER}).value.startswith("<object")


def test_select_paths_and_pushdown():
    record = Labeled({"amount": scalar(10.0, TX), "subject": scalar("hi", RF)}, frozenset({TX}))
    lst = Labeled((record,), frozenset({TX}))
    assert select(lst, "amount").plain() == [10.0]
    assert select(lst, "[0].amount").all_sources() == {TX}
    assert select(lst, "[0].subject").all_sources() == {RF, TX}
    assert select(lst, "") is lst
    tainted = Labeled((record,), frozenset({RF}))  # ancestor taint flows down on projection
    assert RF in select(tainted, "[0].amount").all_sources()
    assert select(lst, "[0]").all_sources() == {TX, RF}


@pytest.mark.parametrize("path", ["nope", "[5]", "amount.x", "bad path!", "[0].amount[1]"])
def test_select_errors(path):
    lst = Labeled((Labeled({"amount": scalar(1, TX)}, frozenset({TX})),), frozenset({TX}))
    with pytest.raises(ProvenanceError):
        select(lst, path)


def _tx(sender, amount, subject):
    return Labeled(
        {"sender": scalar(sender, TX), "amount": scalar(amount, TX), "subject": scalar(subject, RF)},
        frozenset({TX}),
    )


def test_filter_on_trusted_field_adds_no_untrusted_taint():
    lst = Labeled((_tx("A", 10.0, "m1"), _tx("B", 4.0, "m2")), frozenset({TX}))
    kept = filter_items(lst, "sender", "eq", scalar("A", USER))
    assert kept.plain() == [{"sender": "A", "amount": 10.0, "subject": "m1"}]
    assert select(kept, "[0].amount").all_sources() == {TX, USER}


def test_filter_on_untrusted_field_taints_every_kept_item():
    lst = Labeled((_tx("A", 10.0, "Spotify"), _tx("B", 4.0, "Rent")), frozenset({TX}))
    kept = filter_items(lst, "subject", "contains", scalar("spot", USER))
    assert len(kept.value) == 1
    assert RF in select(kept, "[0].amount").all_sources()


@pytest.mark.parametrize(
    ("cmp", "value", "expected"),
    [("ne", 10.0, ["B"]), ("lt", 5, ["B"]), ("le", 4.0, ["B"]), ("gt", 5, ["A"]), ("ge", 10.0, ["A"])],
)
def test_filter_comparisons(cmp, value, expected):
    lst = Labeled((_tx("A", 10.0, ""), _tx("B", 4.0, "")), frozenset({TX}))
    assert select(filter_items(lst, "amount", cmp, scalar(value, USER)), "sender").plain() == expected


def test_filter_errors():
    with pytest.raises(ProvenanceError):
        filter_items(scalar(1, USER), "x", "eq", scalar(1, USER))
    lst = Labeled((_tx("A", 10.0, ""),), frozenset({TX}))
    with pytest.raises(ProvenanceError):
        filter_items(lst, "sender", "lt", scalar(1, USER))


def test_compute_ops_and_sources():
    a, b = scalar(10.0, TX), scalar(4, USER)
    assert compute("sub", a, b).plain() == 6.0
    assert compute("add", a, b).all_sources() == {TX, USER}
    assert compute("mul", a, b).plain() == 40.0 and compute("div", a, b).plain() == 2.5
    with pytest.raises(ProvenanceError):
        compute("div", a, scalar(0, USER))
    with pytest.raises(ProvenanceError):
        compute("add", a, scalar(True, USER))
    with pytest.raises(ProvenanceError):
        compute("mul", scalar(1e308, USER), scalar(1e308, USER))


def test_extracted_inherits_everything_shown():
    out = extracted({"iban": "DE1", "total": 3}, [scalar("file text", RF)], scalar("find iban", PLANNER))
    assert out.all_sources() == {RF, PLANNER}
    assert select(out, "iban").all_sources() == {RF, PLANNER}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("GB29NWBK60161331926819", USER),
        ("gb29nwbk60161331926819", USER),
        ("Refund", PLANNER),
        ("", PLANNER),
        (12.0, USER),
        (12, USER),
        (1050, USER),
        (10, USER),
        (4.0, PLANNER),
        (True, PLANNER),
        (None, PLANNER),
    ],
)
def test_ground_literal(value, expected):
    prompt = "Send back the difference to GB29NWBK60161331926819; we spent 12.00, total 1,050 and 10% more."
    assert ground_literal(value, prompt) == expected


def test_system_source_exists():
    assert SYSTEM.trusted and SYSTEM.kind == "SYSTEM"
