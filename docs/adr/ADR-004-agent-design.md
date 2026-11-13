# ADR-004: The defense end-to-end (`provguard.agent`)

Status: accepted 2026-11-13. Supersedes nothing; implements design §1–§2 of `docs/design/core.md` and recon §7.

## Context
Phase 2b needs an LLM planner and an LLM extractor around `provguard.core.PlanRunner`, inside an AgentDojo
pipeline, so the policy layer can be measured against the baselines with the same driver (`run_arm`).

## Decisions
1. **Single-shot blind planner (P-LLM).** One request → one JSON plan; the planner never sees tool outputs.
   This is the strongest isolation (no injected text can reach the planner) and the main utility cost: no
   data-dependent branching. The cost is measured, not argued away (`docs/FAILURES.md`).
2. **Prompt examples use a fictional calendar/notes domain**, never the benchmark's tools or tasks, so the prompt
   teaches the plan language and cannot encode AgentDojo tasks (rule 3). The planner sees tool names, argument
   names and the tools' own docstrings (`tool_specs`), which are part of the user-task spec.
3. **Extractor (Q-LLM) has no tools and sees only the documents, the instruction and the schema.** Documents are
   delimited and declared as data. Its output is labelled with the union of its inputs' sources (design §2.5), so
   a successful injection of the extractor can at most change *values* whose provenance is already untrusted.
4. **Fail closed everywhere**: invalid plan after two attempts → no tool runs; tool error → run stops; extractor
   returns bad JSON → core validation fails → one retry → stop. Every stop produces an assistant message that says
   what was not done and why.
5. **AgentDojo message emission (OD5 resolved):** one assistant message containing the plan JSON (for the log),
   then per executed call an assistant message with exactly one `tool_calls` entry followed by a `tool` message
   (so `functions_stack_trace_from_messages` and the shipped utility checks work unchanged), then one final
   assistant text (`model_output_from_messages` reads the last message). Denied or unconfirmed calls emit no
   `tool_calls`, so trace-based security checks see no action. The full `GuardTrace` is also returned in
   `extra_args["provguard"]`.
6. **Modes**: `provguard_strict` (CONFIRM → deny; utility lower bound) and `provguard_permissive` (CONFIRM →
   approve; ASR upper bound for a careless user). Both are `DEFENSES` in `provguard.bench.pipelines` and run
   through the same `run_arm`. Pipeline name `provguard-<mode>-<model>` keeps the `important_instructions`
   prose-name rule (ADR-003 §5).
7. **`reduce` added to the plan language** (`sum|count|min|max`, optional `path`). Without it a total needs
   either an unbounded `compute` chain or LLM arithmetic. Provenance: union of every item examined. The first
   live planner call produced `reduce` over records instead of amounts; `path` sugar was added the same day.
8. **One model for planner and extractor by default** (`openai/gpt-oss-120b`, `reasoning_effort: low`); a
   separate `extractor_client` is supported for a small-model Q-LLM later. `response_format: json_object` is
   requested on both.

## Alternatives rejected
Re-planning after each tool result (a "ReAct with provenance" loop): the planner would read tool outputs and the
isolation argument of §1 collapses into prompt-level defenses. A typed mini-language with `if`: deferred; the
measured failures decide whether it is worth it (master prompt §5.8 fallback remains available).

## Consequences
- Benign utility on banking will be structurally limited (design §4 predicted ≈8/16 in strict mode); any
  number is `[PENDING]` until `results/` has the arm.
- Each case costs ≈1 planner call (≈1.6k prompt tokens for banking) plus one extractor call per `extract`.

## Amendment 1 (2026-11-13): the planner sees output schemas, never data
Human decision after F2: the planner is blind to *data*, not to *schemas*. `policies/schemas/<suite>.yaml`
gives every tool a typed `returns` line and shared result types (for banking: `Transaction` fields, date format,
and the ledger convention that the owner's side is `"me"` or the own IBAN). Rules: written from tool source and
return types only; one entry per tool (a test asserts the set equals the suite's tools); no task text, no
injection content; applied to every request. `ToolSpec.returns` carries it; `render_tools` prints it;
`--no-schemas` (pipeline name `provguard-<mode>-noschema-…`) keeps the ablation runnable.
Measured on the benign smoke subset (5 tasks, strict, gpt-oss-120b): 0/5 without schemas → 1/5 with
(`results/*smoke-noschema.json`, `*smoke.json`); `user_task_1` False → True.

## Amendment 2 (2026-11-13): provider JSON failures fail closed
Groq can answer JSON mode with HTTP 400 "Failed to generate JSON". Planner counts it as a failed attempt;
extractor returns `None` (core then retries once and stops). Other errors still propagate.

## Amendment 3 (2026-11-13): human decisions on OD7 (items 1–3; item 4 deferred)
1. **Today's date is a SYSTEM value, read like a production clock.** New plan value `{"sys": "today"}`
   (`core.plan.Sys`), resolved by `PlanRunner(system_values=...)` and labelled `SYSTEM`. The adapter's
   `today_from_env` uses the environment's own clock when it has one (`env.calendar.current_day`, present in
   AgentDojo suites with a calendar) and otherwise the process clock. Verified in agentdojo==0.1.35: the banking
   environment defines **no** current date (no field, no tool, nothing in the system message), so banking runs
   use the real date. No date is hardcoded; the ground-truth dates in the user tasks were not used. The value
   never enters the planner prompt, so the cache key and cassettes do not change from day to day. Banking date
   arguments allow `SYSTEM`. The source used is stored in `GuardTrace.today_source`.
2. **Prompt rule 4 reworded**: ask only when a value exists nowhere (request, readable tool results, system
   values); a short subject/label may be a planner literal (already allowed by policy as `PLANNER`).
3. **Free-text matching goes through the extractor, not `filter contains`**: extract the record's identifier
   from the list, then `filter` on it by reference. No new operator: `extracted` labels the identifier with the
   union of everything the extractor read (including untrusted subjects), and `filter_items` adds the value's
   sources to every kept item. So anything selected by an untrusted description is untrusted, the same rule as
   `select`. Property test: `test_match_derived_from_untrusted_text_taints_every_selected_item`.
   Normalised `contains` was rejected: it still fails on "New Year's gift" vs "New year gift".
4. **`reduce`/`select` path strings are unlabelled.** A path is plan text written by the planner, and the
   planner only ever sees trusted inputs (the user prompt, tool schemas, system text). It names *where* to look,
   not *what* was found; the data it reaches keeps its own labels and pushed-down ancestor labels, which is
   what the reduce property test asserts. Labelling paths `PLANNER` would add a trusted source to every value
   and change no verdict.
5. **Traceability**: `UsageSummary` now also records `cached_*_tokens`, the original live usage stored with
   each cached response, so a results file written by a cached rerun still shows what the calls cost. Results
   also record `guard.requests_reaching_guarded_call`.


## Amendment 4 (2026-11-13): final planner iteration, then freeze as `planner-v1`
Last round of generic fixes (human stop rule: no further fix-rerun cycles):
- **F8 optional extraction fields**: `FieldSpec.optional`; a null/absent optional field validates to null. A null
  value reaching a tool call is handled *after* the policy decision (so the decision still sees the argument and
  its sources; the C1 property test caught the first version that skipped mediation): an optional tool argument
  is omitted, a required one stops the run.
- **F5 subject matching**: rule 2 forbids `filter` on free text; the fictional worked example now shows
  "extract the id from the list, then filter on the id by reference".
- **F9 / F11**: `reduce` works on the list of records with a field-name `path`; no `select` first, no index;
  paths contain only field names, dots and `[index]`.
**Freeze.** `src/provguard/agent/prompts.py`, `policies/schemas/`, `policies/banking.yaml` and
`policies/trust.yaml` at git tag `planner-v1` are frozen until Phase 9. Failures found after the tag are
documented in `docs/FAILURES.md` and not fixed. Measurement protocol: `docs/PROTOCOL.md`.
