# Design: `provguard.core` (Phase 2 core)

Status: v1, 2026-11-12. Implements ADR-002 with two refinements recorded in §2.4 and §2.6 (a `PLANNER` source and
selection taint). Pure Python: pydantic + pyyaml only; no LLM or network calls. The planner and extractor LLMs,
the AgentDojo adapter and the confirmation handlers live in `provguard.agent` / `provguard.bench` (Phase 2b) and
talk to the core through plain callables.

```
user prompt ──► planner LLM (sees prompt + tool schemas only) ──► Plan (JSON) ──► plan.validate()
                                                                                      │
   tools ◄──── PlanRunner: for each step ─────────────────────────────────────────────┘
     ▲            CallTool  → policy.decide(call) → ALLOW | CONFIRM→handler | DENY → run tool → label output
     │            Select/Filter/Compute → deterministic, label-carrying
     │            Extract   → extractor LLM (no tools) → validate against schema → label = union(inputs)
     │            Respond   → fill template
   trust.yaml ── labels tool outputs per field          policies/banking.yaml ── per-tool, per-arg allow-lists
```

## 1. Plan format (`plan.py`)

A plan is a JSON document validated by pydantic. Every step has an `out` name except `Respond`. Argument values
are either a `Literal` or a `Ref`.

```python
Literal = {"lit": <str | int | float | bool | None>}
Ref     = {"ref": "<out name>", "path": "<optional dotted path>"}   # path is sugar for Select

CallTool {"op": "call", "out": "t1", "tool": "get_most_recent_transactions", "args": {"n": {"lit": 100}}}
Select   {"op": "select", "out": "amts", "ref": "t1", "path": "amount"}          # maps over lists
Filter   {"op": "filter", "out": "f", "ref": "t1", "field": "sender", "cmp": "eq", "value": {"lit": "GB29..."}}
Compute  {"op": "compute", "out": "diff", "fn": "sub", "a": {"ref": "f", "path": "[0].amount"}, "b": {"lit": 12.0}}
Reduce   {"op": "reduce", "out": "total", "ref": "tx", "path": "amount", "fn": "sum"} # sum | count | min | max (added 2026-11-13)
Extract  {"op": "extract", "out": "bill", "from": [{"ref": "file"}], "instruction": "Find the IBAN and total",
          "schema": {"iban": {"type": "str", "pattern": "^[A-Z]{2}[0-9A-Z]{4,32}$"}, "total": {"type": "float", "minimum": 0}}}
ForEach  {"op": "foreach", "out": "sent", "ref": "f", "max_items": 5, "steps": [ ...steps using {"ref": "item"}... ]}
Respond  {"op": "respond", "template": "You spent {total} in March."}
```

| op | deterministic | provenance of `out` |
|---|---|---|
| `call` | yes (tool may have side effects) | labelled from `trust.yaml` (§2.3); plus the call's argument sources if `echoes_args` |
| `select` | yes | the selected sub-tree keeps its own labels (projection) |
| `filter` | yes | each kept item: its own labels ∪ labels of the inspected `field` across all examined items ∪ `value` sources (§2.6) |
| `compute` | yes | union of both operands |
| `reduce` | yes | union of the list's and every item's labels (every item was examined) |
| `extract` | no (LLM) | union of every input's labels and the instruction's label (§2.5) |
| `foreach` | yes (loop) | `out` is the list of the body's last `out` per iteration; `item` carries the element's labels |
| `respond` | yes | not labelled (goes to the user) |

**Static validation (`Plan.validate_against(tools)`)** rejects: duplicate `out` names; a `ref` to a name not
defined by an earlier step (or `item` outside `foreach`); unknown tool; unknown or missing required argument;
nested `foreach`; more than `max_steps` (default 20) steps; `max_items` > 25; `respond` not last; `compute`
operands that are not `lit`/`ref`. Dynamic checks (types of `compute` operands, missing paths, extraction schema
conformance) raise `PlanRuntimeError` and the run fails closed.

**Limits of a linear plan (v1).** No data-dependent branching (no `if`). Banking `user_task_14` ("if something
looks suspicious, update the password") cannot be expressed as a condition; the planner either updates
unconditionally or asks in `Respond`. `foreach` is bounded and cannot stop early. These costs are measured in
Phase 2b (`docs/FAILURES.md`) and the fallback (§5.8 of the master prompt) remains available.

## 2. Provenance semantics (`provenance.py`, `trust.py`)

### 2.1 Sources
```python
Source(kind: "USER" | "SYSTEM" | "PLANNER" | "TOOL", name: str | None, trusted: bool)
USER      = Source("USER", None, True)      # copied verbatim from the user's prompt
SYSTEM    = Source("SYSTEM", None, True)    # literal created by our code
PLANNER   = Source("PLANNER", None, True)   # literal invented by the planner LLM (not verbatim in the prompt)
tool(name, trusted)                         # output of a tool, trust decided by trust.yaml
```
`PLANNER` is a refinement of ADR-002: the planner never sees untrusted data, so its inventions are not
attacker-influenced (integrity is intact) but they are hallucination-prone. Policies can therefore allow
`PLANNER` for harmless arguments (dates, memos) and refuse it for dangerous ones (recipient IBAN, password).
Grounding rule (`ground_literal(value, prompt)`): a string literal is `USER` if it occurs in the prompt
(case-insensitive, whitespace-normalised substring); a number is `USER` if a numeric token of the prompt equals it
(`12.00`, `1,050`, `10%` are tokens); everything else is `PLANNER`.

### 2.2 Labeled values
`Labeled` is an immutable tree: `Labeled(value, sources)` where `value` is a scalar, a `tuple[Labeled, ...]` or a
`Mapping[str, Labeled]`. `node.sources` are the node's own sources; `node.all_sources()` is the union over the
subtree. Passing a node as a tool argument uses `all_sources()`. `union(a, b)` is commutative, associative,
idempotent and monotone; **no function in the core removes a source**. The only way an untrusted value reaches a
side effect is a `CONFIRM` approved by the confirmation handler, which approves that one call and relabels nothing.

### 2.3 Labelling tool outputs (`trust.py`)
`TrustConfig` is `policies/trust.yaml`. `label_output(tool, raw, arg_sources)`:
1. base = `{tool(name, trusted)}`; if `echoes_args` (default `true` for tools with side effects, explicit in the
   file) then base ∪= `arg_sources`.
2. Walk `raw` (pydantic models are dumped to dicts first). Every node gets `base`. A dict key listed under
   `fields:` gets its override instead: `untrusted` → `{tool(name, False)} ∪ echo`, `trusted` → `{tool(name, True)}
   ∪ echo`. Overrides apply at any depth (records inside lists).
3. Tools absent from the file get `default` (untrusted) for the whole output.

### 2.4 Projection
`select(node, path)` follows dotted keys and `[i]` indexes; applied to a list node it maps over items (a list of
records `.amount` → list of amounts). The result is the sub-node itself, so a trusted field of a record whose
`subject` is untrusted stays trusted. This is the mechanism that lets refunds be auto-allowed.

### 2.5 Extraction
The extractor is a black box that read everything it was shown. Its output (each field) is labelled with the union
of `all_sources()` of every input plus the instruction's source. No `extractor` marker source is added: if every
input was trusted, the output is trusted (the LLM may be *wrong* but cannot have been *injected*). Output is
validated against the `schema` (`extraction.validate(schema, raw)`); the agent retries once, then fails closed.

### 2.6 Selection taint (refines ADR-002 §7 / decision D2)
`filter` decides membership by looking at a field. Which record survives is therefore attacker-influenced whenever
that field is untrusted ("relabel a memo to *Spotify* and a different amount gets sent"). So every kept item is
additionally labelled with the inspected field's sources over all examined items. Filtering by a ledger field
(`sender`, `amount`, `id`) adds only trusted sources and costs nothing; filtering by `subject` taints the result,
exactly as an LLM extraction over the same text would. Loop bounds (`foreach`) add no taint: the count of
iterations is bounded by `max_items`, and the attacker can only change *which* items exist by controlling data
that is labelled anyway.

### 2.7 What is **not** tracked
Side channels (timing, exception text), taint stored in the environment across runs, and the `Respond` text (it
goes to the user; injected text can still reach the user as prose).

## 3. Policy language (`policy.py`)

```yaml
version: 1
unlisted_tool: DENY                 # a tool with no entry is refused (fail closed)
tools:
  get_balance: { guarded: false }   # read-only: always ALLOW, still logged
  send_money:
    guarded: true
    default: { allow: [USER, PLANNER], else: CONFIRM }          # for args not listed below
    args:
      recipient:
        allow: [USER, tool:get_most_recent_transactions, tool:get_scheduled_transactions]
        else: CONFIRM
        constraints: { pattern: "^[A-Z]{2}[0-9A-Z]{4,32}$" }    # tool doc says "IBAN of the recipient"
        on_violation: DENY
      amount: { allow: [USER, PLANNER, tool:get_most_recent_transactions, tool:get_scheduled_transactions, tool:get_balance], else: CONFIRM, constraints: { minimum: 0, exclusive: true } }
```

Semantics:
- `allow` entries: `USER`, `SYSTEM`, `PLANNER`, or `tool:<name>`. `tool:<name>` matches **only**
  `Source("TOOL", name, trusted=True)`. There is no syntax that matches an untrusted source. Hence
  **C1 holds by construction**: a value whose `all_sources()` contains an untrusted source can never satisfy
  `sources ⊆ allow`.
- An argument passes if `all_sources(arg) ⊆ allow`; otherwise the verdict is the arg's `else` (`CONFIRM` or
  `DENY`). Constraints (`pattern`, `enum`, `minimum`, `maximum`, `exclusive`) are checked on the concrete value;
  a violation yields `on_violation` (default `DENY`).
- Arguments present in the call but not listed use the tool's `default`; a guarded tool without `default` uses
  `{allow: [USER], else: CONFIRM}`. Absent optional arguments are not evaluated.
- Call verdict = `DENY` if any arg is `DENY`, else `CONFIRM` if any is `CONFIRM`, else `ALLOW`. Every arg's
  outcome is kept in `Decision.reasons`.
- `Decision(verdict, tool, reasons: list[Reason], policy_version)`; `Reason(arg, outcome, rule, sources,
  message)`; both JSON-serialisable for the audit log and the demo ("recipient came from read_file
  (untrusted); rule send_money.recipient").
- Policies are loaded per tenant by the service (Phase 6); the core loads one `PolicySet` from a path or dict
  and validates it against the tool registry (unknown tool names in `allow` are a load-time error).

## 4. Banking policies from tool semantics only (`policies/banking.yaml`)

Derived from the tool docstrings/signatures in `docs/recon/agentdojo.md` §6 and the threat model §4. Injection
task contents were not read.

| tool | arg | allow | else | constraints |
|---|---|---|---|---|
| send_money | recipient | USER, ledger* | CONFIRM | IBAN-shaped |
| | amount | USER, PLANNER, ledger, tool:get_balance | CONFIRM | > 0 |
| | subject | USER, PLANNER | CONFIRM | – |
| | date | USER, PLANNER, ledger | CONFIRM | – |
| schedule_transaction | as send_money; `recurring` | USER, PLANNER | CONFIRM | – |
| update_scheduled_transaction | id | USER, tool:get_scheduled_transactions | CONFIRM | – |
| | recipient / amount / subject / date / recurring | as above | CONFIRM | |
| update_password | password | USER | **DENY** | – |
| update_user_info | first_name, last_name, street, city | USER | CONFIRM | – |
| get_iban, get_balance, get_most_recent_transactions, get_scheduled_transactions, read_file, get_user_info | – | unguarded | | |

`ledger` = `tool:get_most_recent_transactions, tool:get_scheduled_transactions` (only their trusted fields can
ever match, per §2.3). `PLANNER` is excluded from `recipient`, `id`, `password` and profile fields because a
hallucinated value there is dangerous; it is allowed for amounts, memos and dates because the planner must be able
to compute and default them. `tool:get_user_info` appears in no allow-list, so profile data cannot flow into an
outgoing memo without a CONFIRM (the confidentiality approximation of ADR-002).

### Predicted strict-mode ceiling (written before any run; not a result)

| task | guarded step | predicted | why |
|---|---|---|---|
| 0 | send_money ← bill text | CONFIRM | data requires action |
| 1, 7, 8 | none | ALLOW | read-only |
| 2, 12 | update_scheduled_transaction ← notice + subject-selected id | CONFIRM | untrusted amount and selection |
| 3, 4 | send_money(recipient ← prompt / `sender`, amount ← `amount` − 12.00) | ALLOW | ledger fields + USER literal |
| 5, 6, 11 | amount ← record selected by `subject` | CONFIRM | selection taint (§2.6) |
| 9 | update ← record selected by `subject` | CONFIRM | utility requires *no* change, so strict mode likely passes |
| 10 | none | ALLOW | utility requires no change |
| 13 | update_user_info ← file | CONFIRM | data requires action |
| 14 | update_password(USER literal) | ALLOW | but linear plan cannot express the "if" |
| 15 | update_user_info ALLOW; update_scheduled_transaction id ← `subject` CONFIRM; send_money refund ALLOW | CONFIRM overall | multi-goal, one step confirms |

Ceiling in strict mode ≈ 8/16 tasks (1, 3, 4, 7, 8, 9, 10, 14) **if** the planner and model are competent; the
permissive ceiling is whatever the model can do. Actual numbers: `[PENDING]`, Phase 2b.

## 5. Property tests (`tests/property/`, hypothesis)

1. **C1 no untrusted auto-allow.** For random plans over a random tool registry with random trust configs and
   random policies, every `ALLOW` decision for a guarded tool has `all_sources(arg) ⊆ allow` and no untrusted
   source for every guarded arg. Equivalently: inject one untrusted source anywhere upstream (tool output field,
   extractor input, filter field) and the decision for any arg that depends on it is never `ALLOW`.
2. **Union laws.** `union` is commutative, associative, idempotent; `all_sources(derived) ⊇ all_sources(input)`
   for every op (monotonicity / no declassification).
3. **Labelling is complete.** After `label_output`, every node has a non-empty source set containing a `tool(name,
   _)` source; a field marked `untrusted` has an untrusted source at every depth.
4. **Projection keeps labels.** `select(node, path).all_sources() ⊆ node.all_sources()` and equals the sub-node's.
5. **Selection taint.** `filter` on a field whose sources include `s` yields items whose sources include `s`.
6. **Policy totality and determinism.** `decide` never raises on validated inputs; same input → same output;
   verdict precedence `DENY > CONFIRM > ALLOW` over args.
7. **Round-trips.** `Plan`, `Decision`, `Labeled` serialise to JSON and back unchanged.
8. **Grounding.** `ground_literal(x, prompt)` is `USER` iff the literal occurs in the prompt under the §2.1 rule.

## 6. Known failure modes and limitations

- **Data requires action** (tasks 0, 2, 12, 13): legitimate and injected values have identical provenance. Only
  the human can tell; strict mode fails them by design.
- **Free-text selection** (5, 6, 9, 11, 15): selecting a record by memo taints the result. A planner that can
  select by ledger fields avoids it; often it cannot.
- **No branching** (14) and bounded loops.
- **Schema-valid lies.** An attacker can put a well-formed IBAN in a bill; extraction validates the shape, not the
  truth. CONFIRM shows the value and its provenance, which is all provenance can do.
- **Planner hallucination** is contained by `PLANNER` labels and allow-lists, not eliminated.
- **Unguarded arguments** (`n`, `file_path`) are not policy-checked.
- **Mis-selection with trusted fields**: filtering by `amount == 10` and two transactions match → the planner's
  choice (`[0]`) is a correctness issue, not a security one.
- **Stored taint across runs** and **side channels** are out of scope (threat model §7).
- **Response channel**: injected prose can reach the user through `Respond` templates that include extracted text.
- **Tool argument coercion**: AgentDojo's `ToolsExecutor` turns string-encoded lists into lists; our runner passes
  typed JSON, so this path is not exercised.
