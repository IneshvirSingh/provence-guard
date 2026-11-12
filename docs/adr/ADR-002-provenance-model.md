# ADR-002: Provenance model

Status: accepted (2026-11-12). Implemented by `src/provguard/core` (Phase 2); detailed semantics in
`docs/design/core.md`.

## Context

Indirect prompt injection works because the model cannot tell *who wrote* the text it is reading. CaMeL shows
that tracking where every value came from, and checking those labels deterministically before side effects,
removes the model from the trust decision. We need the smallest model of "where it came from" that still lets
us write defensible policies for the banking tools and prove a property about them.

## Decision

1. **Source** is a sum type: `USER` (the prompt), `SYSTEM` (literals our code creates), `TOOL(name, trusted)`.
   `trusted` is decided by `policies/trust.yaml`, per tool and optionally per output field.
2. **Labeled[T]** is an immutable value plus `sources: frozenset[Source]`. Every operation that derives a value
   takes the **union** of its inputs' sources. There is no operation that drops a source (no declassification).
   Human confirmation approves one tool call; it does not relabel.
3. **Per-field labels on tool outputs.** A tool result is labelled as a tree: record fields get their own
   labels from the trust config (e.g. `Transaction.subject` untrusted, `Transaction.amount` trusted). Projecting a
   field (`Select`) keeps only that field's sources. This is what lets refund tasks be auto-allowed while
   free-text-driven tasks are confirmed.
4. **Tool outputs inherit argument sources** when `echoes_args: true` (and by default for side-effecting tools),
   because return messages echo their inputs.
5. **LLM extraction is a black box**: the extractor's output carries the union of the sources of *everything*
   it was shown, plus `TOOL(extractor, trusted=false)`. Planner literals are `USER`-sourced only when they were
   copied from the prompt; the planner never sees anything else, so there is nothing else to copy.
6. **Policies** are per tool, per argument: an allowed set of sources and a verdict (`CONFIRM` or `DENY`) when a
   value's sources are not a subset of it. Decisions are `ALLOW | DENY | CONFIRM` with a machine-readable reason
   (tool, argument, offending sources, rule id). Unlisted arguments get the tool's default.
7. **No control-flow taint for deterministic steps** (CaMeL NORMAL mode). Plans are linear in v1, so the only
   data-dependent selection happens inside extraction, which is already tainted by rule 5.

## Alternatives rejected

- *Per-tool trust only.* Would label every transaction untrusted because of its memo, confirming almost every
  banking task; the ledger-attested fields are genuinely trustworthy.
- *Readers/capabilities lattice (CaMeL).* Needed for a general confidentiality story; for this suite, naming the
  allowed sources of outgoing free-text arguments (`subject` ⊆ {USER}) gives the same protection with one label
  dimension. Listed as future work.
- *Taint bits instead of source sets.* A single `untrusted` bit cannot produce the explanation the demo needs
  ("recipient came from `read_file(bill.txt)`") and cannot express per-tool allow-lists.
- *String matching of tool outputs in arguments* (the fallback design, §5.8 of the master prompt). Weaker: misses
  transformed values and cannot distinguish trusted from untrusted fields. Kept as the scope-cut fallback.

## Consequences

- The invariant to property-test: for any plan and any tool outputs, a value whose sources contain a
  `TOOL(_, trusted=False)` can never produce `ALLOW` for a guarded argument.
- Utility cost is structural, not a bug: tasks whose guarded arguments must come from untrusted text will be
  CONFIRMed. Strict and permissive modes bound the cost; the confirmation rate quantifies it.
- Explanations are free: the reason object *is* the provenance.

## Amendment 1 (2026-11-12, with the core implementation)

Two refinements, both argued in `docs/design/core.md`:

1. **`PLANNER` source.** Planner literals that do not occur verbatim in the user's prompt are labelled
   `PLANNER` (trusted, since the planner never sees untrusted data) instead of `USER`, so policies can refuse
   invented recipients, ids, passwords and profile values while still allowing invented dates, memos and computed
   amounts. Grounding rule in `provenance.ground_literal`.
2. **Selection taint.** Decision 7 ("no control-flow taint for deterministic steps") is narrowed: a deterministic
   `filter` adds the inspected field's sources (over all examined items) to every kept item, because *which*
   record survives is attacker-influenced when the field is untrusted. Loop bounds still add no taint.
   Implemented in `provenance.filter_items`, property-tested in `tests/property/test_provenance_props.py`.
