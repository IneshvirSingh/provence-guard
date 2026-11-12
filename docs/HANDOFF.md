# HANDOFF.md — for the next model/session

Last updated: 2026-11-12, end of session 1 (Claude Fable 5.1). Fable is available until 2026-11-17; Claude Opus
5.5 continues afterwards. Read `CLAUDE.md`, `PLAN.md`, `PROGRESS.md`, `HUMAN_TODO.md` first.

## State
- Phase 0 complete and pushed; **GATE 0 awaiting the human's "go"** (decisions D1–D4 in `HUMAN_TODO.md` §3).
- `make check` green; compose services healthy; pre-commit (incl. gitleaks) installed.
- No LLM calls have been made. No API keys exist in the Codespace yet.
- AgentDojo 0.1.35 is **not** installed in the project env (it is an extra: `uv sync --extra bench`). Recon used a
  scratch venv; everything learned is in `docs/recon/agentdojo.md`.

## Exact next task (after "go")
Write `docs/design/core.md`, then implement `src/provguard/core/` against it. Outline the design doc as:
1. **Plan format** (pydantic): `Plan(steps: list[Step])`, steps = `CallTool(name, args: dict[str, Literal|Ref])`,
   `Extract(from_ref, schema: JSON-schema-ish, instruction, fields: list[path] | None)`, `Select(ref, path)`
   (deterministic projection, keeps only that field's sources), bounded `ForEach(ref, max_items, steps)`,
   `Respond(template_with_refs)`. Static validation: refs defined before use, tool names/args match schemas,
   max steps, no nested ForEach in v1. Document the no-branching limitation and what it costs (which banking
   tasks need branching: user_task_14 "if suspicious").
2. **Provenance semantics**: `Source = USER | SYSTEM | TOOL(name, trusted)`; `Labeled[T]`; per-field labelling of
   tool outputs from `policies/trust.yaml` (lists of records → each item's fields); `echoes_args`; extractor
   outputs = union(all shown inputs) ∪ TOOL("extractor", False); union everywhere; no declassification.
   Decide and write down: how to label dict/list structures returned by tools, and what `Select` on a list does
   (maps over items).
3. **Policy language** (YAML, versioned, per tenant): per tool → per arg → `allow_sources` (USER, SYSTEM,
   `tool:<name>` meaning the trusted output of that tool), `else: CONFIRM | DENY`, optional value constraints
   (regex e.g. IBAN shape, enum, numeric range), tool-level `default_arg_policy`, `unlisted_tool: DENY|CONFIRM`.
   Decision object: `ALLOW | DENY | CONFIRM` + reason {tool, arg, sources, rule_id, message}. Evaluation order:
   DENY beats CONFIRM beats ALLOW across args.
4. **Per-tool policies from tool semantics only** (never from injection tasks): `send_money`, `schedule_transaction`,
   `update_scheduled_transaction`, `update_password`, `update_user_info`. Expected: recipient/amount allow
   {USER, tool:get_most_recent_transactions, tool:get_scheduled_transactions} (trusted fields only, which the
   label system guarantees) else CONFIRM; `subject` allow {USER, SYSTEM} else CONFIRM; `password` {USER} else
   DENY; profile fields {USER} else CONFIRM; `id` {USER, tool:get_scheduled_transactions} else CONFIRM.
   Walk every banking user task (table in `docs/recon/agentdojo.md` §6) and predict ALLOW/CONFIRM per step;
   that prediction is the expected strict-mode utility ceiling and must be written down **before** running.
5. **Property-test list** (hypothesis): C1 no untrusted auto-allow under arbitrary composition (union, select,
   echo, extract); union is commutative/associative/idempotent and monotone; labelling a tool output never yields
   a field with fewer sources than the trust config implies; policy evaluation is deterministic and total;
   serialisation round-trips; DENY/CONFIRM precedence.
6. **Known failure modes and limitations**: data-requires-action tasks (0, 2, 12, 13), subject-driven selection
   (5, 6, 7, 9, 11), no branching (14), mis-selection of record id, unguarded args, stored taint, extractor
   schema-valid lies (an attacker IBAN that looks like a bill IBAN), planner hallucinating literals that were not
   in the prompt (mitigation: literal must appear verbatim in the prompt or be SYSTEM-typed, decide!).

Then implement `provenance.py`, `plan.py`, `policy.py`, `trust.py` with tests. Keep it under ~800 lines total.

## Open decisions (not yet made)
- OD1 Planner literal provenance: label every planner literal `USER`, or require it to appear verbatim in the
  prompt (else `SYSTEM`-untrusted)? Recommendation: verbatim-or-numeric check, label others as
  `TOOL("planner", trusted=False)`; measure its utility cost.
- OD2 Phase 1 attack naming for Groq models (`important_instructions` needs a `MODEL_NAMES` key in the pipeline
  name). Recommendation: register a subclass with the right prose model name under the same attack name and
  record it in results metadata.
- OD3 Where long benchmark runs execute (Codespace chunks vs GitHub Actions) — ADR-003 after measuring tokens.
- OD4 Whether the `transformers_pi_detector` baseline runs at all before Phase 3 (needs torch).

## Known risks
- Strict-mode banking utility will be structurally low (predicted ≤ ~8/16 tasks auto-allowed). This is expected and
  must be reported, not tuned away.
- Groq free-tier RPD may make a full 169-run arm take several days; the runner must be resumable (Phase 1).
- `OpenAILLM` uses `role="developer"`; Groq compatibility unverified.
- The human has not yet verified any provider's "no payment method" status.

## Things deliberately not done
- No `docs/design/core.md`, no core code (next task). No Phase 1 code. No CI workflow yet (Phase 7, but a minimal
  `ci.yml` running `make check` is cheap and could be added any time).
