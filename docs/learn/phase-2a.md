# Learn: Phase 2a — the core (provenance, plans, policies) without any LLM

## What was built
`src/provguard/core/` (≈660 statements, 99% covered by 89 unit tests and 15 property tests):
- `provenance.py`: `Source`, `Labeled` trees, `union`, `select`, `filter_items`, `compute`, `extracted`,
  `ground_literal`.
- `trust.py`: `TrustConfig` (loads `policies/trust.yaml`) and `label_output` with per-field overrides and echoed
  argument sources.
- `plan.py`: the plan DSL as pydantic models with a discriminated `op` union, plus `Plan.validate_against(tools)`.
- `extraction.py`: schema validation of extractor output (fail closed).
- `policy.py`: `PolicySet` (loads `policies/banking.yaml`), `decide()`, `Decision`/`Reason`.
- `runner.py`: `PlanRunner`, the single mediation point, with injectable tool/extractor/confirmation callables and
  the `confirm_strict` / `confirm_permissive` handlers.

## Why it is shaped this way
The security argument must survive an interview and a property test. So: no code execution (a typed DSL), no
declassification anywhere, a policy syntax in which an untrusted source *cannot* be allowed (`entry_matches`
returns False for any untrusted source), and one function (`PlanRunner._call`) through which every tool call
passes after `decide()`.

## Concepts
1. **Label push-down.** A node's effective sources are its own plus its ancestors'. `select` re-wraps the child
   with the parent's sources, so taint on a record flows to its fields but not to its siblings.
2. **Union-only propagation** is what makes the invariant easy to prove: every operation's output sources are a
   superset of some input's, and the policy check is a subset test.
3. **Fail closed.** Unknown tool → DENY. Malformed value → DENY. Extraction that fails validation twice → the run
   stops. A `CONFIRM` without an approver → stop.
4. **Grounding literals.** The planner can only *copy* from the prompt or *invent*; labelling the two differently
   costs nothing and lets policies refuse invented IBANs.
5. **Property-based testing.** Hypothesis generates random labelled trees, trust configs, policies and plans;
   the tests assert laws (commutativity, monotonicity) and the end-to-end invariant C1, not examples.

## Five interview questions
**Q1. Show me the line that makes "untrusted data can never be auto-allowed" true.**
`policy.entry_matches`: `if not source.trusted: return False`. No allow-list entry matches an untrusted source,
so `sources ⊆ allow` fails for any value touched by untrusted data. `tests/property/test_policy_props.py::
test_c1_allow_implies_every_source_allowed_and_trusted` checks it on random policies; the end-to-end variant runs
random plans through `PlanRunner`.

**Q2. Why does filtering by memo taint the amount, but filtering by sender does not?**
`filter_items` adds the sources of the inspected field to every kept item (selection taint). `subject` is labelled
untrusted by `trust.yaml`; `sender` is ledger-attested. An attacker who can relabel a memo can change which amount
is sent, so the amount must carry that influence. CaMeL's NORMAL mode would not do this; we chose the stricter rule
because it costs nothing on tasks that can be solved from ledger fields.

**Q3. What happens on `user_task_0` ("pay the bill")?**
`read_file` → extractor → `send_money(recipient, amount)`: both args carry `tool:read_file(untrusted)`, the
decision is `CONFIRM` with the reason `send_money.recipient: sources ['PLANNER', 'tool:read_file(untrusted)']
not in allowed [...]`. `confirm_strict` denies (utility lost), `confirm_permissive` pays (attack risk measured).
See `tests/unit/test_runner.py::test_bill_payment_is_confirmed_strict_denies_permissive_pays`.

**Q4. Why not label extractor output with an "extractor" source?**
Because the LLM can only be injected by what it reads. If every input was trusted, the output may be wrong but not
attacker-controlled; adding a marker would just force CONFIRMs on honest arithmetic. The output inherits the union
of its inputs (`provenance.extracted`), so any untrusted byte it saw is on the label.

**Q5. What can still go wrong?**
`docs/design/core.md` §6: data-requires-action tasks, schema-valid lies (a well-formed attacker IBAN in a bill),
planner hallucination (contained, not removed), unguarded arguments, no branching, stored taint across runs.
