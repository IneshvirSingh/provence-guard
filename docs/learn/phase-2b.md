# Learn: Phase 2b — the defense end-to-end (`provguard.agent`)

## What was built (2026-11-13)
- `agent/prompts.py`: planner and extractor prompts. Examples use fictional calendar tools, never banking.
- `agent/planner.py`: `Planner.plan(prompt, tools)` → one validated `Plan`; JSON mode; one retry that feeds the
  validation error back; `PlannerError` fails closed.
- `agent/extractor.py`: `LLMExtractor` (the Q-LLM): documents delimited as data, no tools, JSON out; core validates
  the schema and retries once.
- `agent/adapter.py`: `ProvenanceGuard` pipeline element (plan → `PlanRunner` → AgentDojo messages) and
  `build_guard_pipeline(client, mode, suite=...)`; `provguard_strict` / `provguard_permissive` are `DEFENSES`.
- Core: `reduce` op (`sum|count|min|max`, optional `path`) so totals need no LLM arithmetic.
- First live planner call (gpt-oss-120b, `user_task_1`): see `docs/FAILURES.md` F1 and F2.

## Concepts
1. **P-LLM / Q-LLM split (CaMeL).** The planner never reads tool output, so injected text can never steer the
   control flow; the extractor reads it but can only produce values, and those values carry untrusted provenance.
2. **Fail closed.** Every failure (bad plan, tool error, bad extraction, denied call) ends with no further side
   effects and an explanation. Utility suffers; security does not.
3. **Trace compatibility.** AgentDojo checks utility and security from the environment state and from the
   `tool_calls` in the assistant messages. The adapter emits exactly one assistant/tool pair per executed call, so
   the shipped checks run unchanged, and nothing for calls that were denied.
4. **Blind planning costs utility in predictable ways.** F2: the planner cannot know that outgoing rows carry
   `sender: me`, so it sums incoming transfers too. A ReAct-style loop would see the data and fix this, at the price
   of exposing the planner to injected text. The trade-off is measured, not assumed.
5. **Prompt hygiene vs benchmark gaming.** The planner sees tool docstrings and argument names (part of the
   environment's contract) but no task texts and no injection contents. Prompt changes are driven only by benign
   failures recorded in `docs/FAILURES.md`.

## Five interview questions
**Q1. Why does a plan have to be written before any tool runs?** So the model that decides *what to do* never
sees untrusted data (`Planner.plan` is called once in `ProvenanceGuard.query`, before `PlanRunner.run`). An
injection in a file can change extracted *values*, which the policy then judges by provenance, but cannot add a
step.

**Q2. What stops the extractor from being the weak link?** It has no tools (`extractor_messages` sends none),
its output is validated against a schema (`validate_extraction`), and every field it returns is labelled with the
union of its inputs' sources (`extracted`). A fooled extractor can only produce untrusted values, which
`send_money.recipient` policy routes to CONFIRM/DENY.

**Q3. How does the defense stay comparable with AgentDojo's baselines?** Same driver (`run_arm`), same suite,
same attack, same model; the adapter emits standard messages so `functions_stack_trace_from_messages` and the
utility checks work. Only the pipeline differs.

**Q4. What did the first live run teach you?** The planner skipped `select amount` before `reduce` (F1); a `path`
sugar made the common case one step. Then it produced 1060 instead of 1050 because the environment's data
semantics (`sender: me`) are invisible to a blind planner (F2). Recorded, not patched around.

**Q5. Why two modes?** `strict` turns every CONFIRM into a denial and bounds utility from below; `permissive`
approves every CONFIRM and bounds attack success from above. The real product sits between them with a human in
the loop; the benchmark reports both ends honestly.
