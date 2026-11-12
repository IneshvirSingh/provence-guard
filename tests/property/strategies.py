"""Hypothesis strategies shared by the property tests."""

from __future__ import annotations

from hypothesis import strategies as st

from provguard.core.provenance import PLANNER, SYSTEM, USER, Labeled, Source, tool

TOOL_NAMES = ["read_file", "ledger", "profile", "web"]

trusted_sources = st.one_of(
    st.just(USER),
    st.just(SYSTEM),
    st.just(PLANNER),
    st.builds(tool, st.sampled_from(TOOL_NAMES), st.just(True)),
)
untrusted_sources = st.builds(tool, st.sampled_from(TOOL_NAMES), st.just(False))
sources = st.one_of(trusted_sources, untrusted_sources)
source_sets = st.frozensets(sources, max_size=5)

scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10_000, max_value=10_000),
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.text(max_size=12),
)
numbers = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
)
keys = st.sampled_from(["amount", "subject", "id", "sender", "memo", "x"])


def labeled_trees(max_leaves: int = 12) -> st.SearchStrategy[Labeled]:
    leaf = st.builds(Labeled, scalars, source_sets)
    return st.recursive(
        leaf,
        lambda children: st.one_of(
            st.builds(Labeled, st.lists(children, max_size=4).map(tuple), source_sets),
            st.builds(Labeled, st.dictionaries(keys, children, max_size=4), source_sets),
        ),
        max_leaves=max_leaves,
    )


def records(n_fields: int = 3) -> st.SearchStrategy[Labeled]:
    """A list of record dicts with the same keys, each field independently labelled."""
    field_names = st.lists(keys, min_size=1, max_size=n_fields, unique=True)

    @st.composite
    def _records(draw: st.DrawFn) -> Labeled:
        names = draw(field_names)
        items = []
        for _ in range(draw(st.integers(0, 4))):
            fields = {name: Labeled(draw(numbers), draw(source_sets)) for name in names}
            items.append(Labeled(fields, draw(source_sets)))
        return Labeled(tuple(items), draw(source_sets))

    return _records()


def raw_json(max_leaves: int = 10) -> st.SearchStrategy[object]:
    return st.recursive(
        scalars,
        lambda c: st.one_of(st.lists(c, max_size=3), st.dictionaries(keys, c, max_size=3)),
        max_leaves=max_leaves,
    )


def all_sources_of(node: Labeled) -> frozenset[Source]:
    return node.all_sources()
