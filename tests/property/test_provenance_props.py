"""Property tests for the provenance core (design §5, items 2-5, 7, 8)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from provguard.core.provenance import (
    PLANNER,
    USER,
    Labeled,
    ProvenanceError,
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
from provguard.core.trust import ToolTrust, TrustConfig
from tests.property.strategies import (
    TOOL_NAMES,
    keys,
    labeled_trees,
    numbers,
    raw_json,
    records,
    source_sets,
    sources,
)


@given(source_sets, source_sets, source_sets)
def test_union_is_commutative_associative_idempotent(a, b, c):
    assert union(a, b) == union(b, a)
    assert union(union(a, b), c) == union(a, union(b, c))
    assert union(a, a) == a
    assert a <= union(a, b) and b <= union(a, b)


@given(labeled_trees())
def test_all_sources_covers_every_node_and_json_roundtrips(node):
    def nodes(n: Labeled):
        yield n
        for c in n.children():
            yield from nodes(c)

    assert all(n.sources <= node.all_sources() for n in nodes(node))
    assert Labeled.from_json(node.to_json()) == node
    assert node.is_trusted() == (node.untrusted_sources() == frozenset())


@given(raw_json(), source_sets)
def test_wrap_labels_uniformly_and_plain_inverts(raw, srcs):
    node = wrap(raw, srcs)
    assert node.plain() == raw
    assert node.all_sources() == (srcs if srcs else frozenset())


@given(records(), keys)
def test_select_never_invents_sources_and_pushes_ancestors_down(lst, key):
    try:
        projected = select(lst, key)
    except ProvenanceError:
        return
    assert projected.all_sources() <= lst.all_sources()
    assert lst.sources <= projected.sources  # ancestor sources are pushed down
    for i, item in enumerate(lst.value):
        child = select(lst, f"[{i}].{key}")
        assert item.value[key].sources | item.sources | lst.sources <= child.sources


@given(
    records(), keys, st.sampled_from(["eq", "ne", "lt", "le", "gt", "ge", "contains"]), numbers, source_sets
)
def test_filter_is_monotone_and_taints_with_the_inspected_field(lst, key, cmp, v, vsrc):
    value = Labeled(v, vsrc)
    try:
        kept = filter_items(lst, key, cmp, value)
    except ProvenanceError:
        return
    assert kept.all_sources() <= lst.all_sources() | value.all_sources()
    inspected = union(*(select(lst, f"[{i}].{key}").all_sources() for i in range(len(lst.value))))
    for item in kept.value:
        assert inspected <= item.sources and value.all_sources() <= item.sources
        assert any(item.value == orig.value for orig in lst.value)


@given(st.sampled_from(["add", "sub", "mul", "div"]), numbers, source_sets, numbers, source_sets)
def test_compute_carries_both_operands(fn, x, sx, y, sy):
    try:
        out = compute(fn, Labeled(x, sx), Labeled(y, sy))
    except ProvenanceError as e:  # division by zero, or overflow to inf (hypothesis found 1 / 2.2e-311)
        assert "zero" in str(e) or "non-finite" in str(e)
        return
    assert out.all_sources() == union(sx, sy)
    assert isinstance(out.value, int | float) and not isinstance(out.value, bool)


@given(raw_json(), st.lists(labeled_trees(6), max_size=3), source_sets)
def test_extracted_inherits_every_input(raw, inputs, isrc):
    out = extracted(raw, inputs, Labeled("instr", isrc))
    expected = union(*(i.all_sources() for i in inputs), isrc)
    assert out.all_sources() == expected
    assert out.plain() == raw


@settings(max_examples=200)
@given(
    raw_json(),
    st.sampled_from(TOOL_NAMES),
    st.booleans(),
    st.booleans(),
    source_sets,
    st.lists(keys, max_size=3, unique=True),
)
def test_label_output_is_complete_and_overrides_untrusted_fields(
    raw, name, trusted, echoes, arg_srcs, untrusted_fields
):
    cfg = TrustConfig(
        version=1,
        tools={
            name: ToolTrust(
                trusted=trusted, echoes_args=echoes, fields=dict.fromkeys(untrusted_fields, "untrusted")
            )
        },
    )
    out = cfg.label_output(name, raw, arg_srcs)
    assert out.plain() == raw

    def nodes(n: Labeled, key: str | None):
        yield n, key
        if isinstance(n.value, dict):
            for k, c in n.value.items():
                yield from nodes(c, k)
        elif isinstance(n.value, tuple):
            for c in n.value:
                yield from nodes(c, key)

    for n, key in nodes(out, None):
        assert any(s.kind == "TOOL" and s.name == name for s in n.sources)
        if key in untrusted_fields:
            assert tool(name, False) in n.sources
        if echoes:
            assert arg_srcs <= n.sources


@given(st.text(max_size=30), st.text(max_size=200))
def test_ground_literal_string_rule(lit, prompt):
    src = ground_literal(lit, prompt)
    needle, hay = " ".join(lit.split()).casefold(), " ".join(prompt.split()).casefold()
    assert src == (USER if needle and needle in hay else PLANNER)


@given(numbers, st.text(max_size=100))
def test_ground_literal_numbers_never_match_absent_tokens(n, prompt):
    assert ground_literal(n, prompt) in (USER, PLANNER)
    assert ground_literal(n, f"{prompt} {n}") == USER  # verbatim token always grounds


@given(sources)
def test_scalar_keeps_exactly_its_sources(s):
    assert scalar(1, s).all_sources() == {s}


@given(records(), st.sampled_from(["sum", "count", "min", "max"]), st.data())
@settings(max_examples=200, deadline=None)
def test_reduce_carries_every_source_on_the_path_of_every_item(recs, fn, data):
    """reduce(select(list, path)) == union of: the list's, every record's and every selected field's sources.

    Nothing examined is dropped (no laundering through aggregation) and nothing unexamined is added.
    """
    from provguard.core.provenance import reduce_items

    names = ["amount"] if not recs.value else sorted(recs.value[0].value)
    key = data.draw(st.sampled_from(names))
    expected = union(
        recs.sources,
        *(item.sources for item in recs.value),
        *(item.value[key].sources for item in recs.value),
    )
    try:
        out = reduce_items(select(recs, key), fn)
    except ProvenanceError as e:
        assert fn in ("min", "max") and not recs.value and "empty" in str(e)
        return
    assert out.sources == expected and out.all_sources() == expected
    if any(not s.trusted for s in expected):
        assert not out.is_trusted()  # one untrusted item or ancestor taints the aggregate


@given(labeled_trees(3).filter(lambda t: isinstance(t.value, tuple)))
@settings(max_examples=100, deadline=None)
def test_reduce_count_carries_all_sources_of_arbitrary_lists(lst):
    from provguard.core.provenance import reduce_items

    out = reduce_items(lst, "count")
    assert out.value == len(lst.value) and out.sources == lst.all_sources()


@given(records(), source_sets.filter(lambda ss: any(not x.trusted for x in ss)), st.data())
@settings(max_examples=200, deadline=None)
def test_match_derived_from_untrusted_text_taints_every_selected_item(recs, text_sources, data):
    """Extractor-based matching (ADR-004 amendment 3): an identifier extracted from untrusted text, used as a
    filter value, makes every kept item (and anything selected or reduced from it) untrusted. Same rule as select:
    no step launders the sources of what decided the selection."""
    from provguard.core.provenance import reduce_items

    if not recs.value:
        return
    key = data.draw(st.sampled_from(sorted(recs.value[0].value)))
    target = data.draw(st.sampled_from(list(recs.value))).value[key].value
    free_text = Labeled("some subject line", text_sources)  # what the extractor read
    ident = select(extracted({"id": target}, [free_text, recs], scalar("find it", PLANNER)), "id")
    assert text_sources <= ident.all_sources() and recs.all_sources() <= ident.all_sources()
    kept = filter_items(recs, key, "eq", ident)
    assert len(kept.value) >= 1
    for item in kept.value:
        assert text_sources <= item.sources and not item.is_trusted()
        for field in item.value:
            assert not select(kept, f"[0].{field}").is_trusted()
    assert not reduce_items(select(kept, key), "count").is_trusted()
