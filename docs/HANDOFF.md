# HANDOFF.md — for the next model/session

Last updated: 2026-11-12, end of session 3 (Claude Fable 5.1). Fable is available until 2026-11-17; Claude Opus
5.5 continues afterwards. Read `CLAUDE.md`, `PLAN.md`, `PROGRESS.md`, `HUMAN_TODO.md` first.

## State
- Phase 0 done (GATE 0 "go"). Phase 2a (design + core) done (mini-GATE 2a "go"). Phase 1 harness code done
  (ADR-003); **no benchmark has run**: blocked on `HUMAN_TODO.md` items 1–2 (Groq/Gemini keys and console
  limits). `results/` is empty; everything numeric is `[PENDING]`.
- `src/provguard/core` is done: see `docs/learn/phase-2a.md` for the module map. 89 unit + 15 property tests,
  99% coverage. Public API in `provguard.core.__init__`.
- `make check` green; compose services healthy; pre-commit (incl. gitleaks) installed.
- No LLM calls have been made. No API keys exist in the Codespace yet.
- AgentDojo 0.1.35 is installed via the `bench` extra (`uv sync --group dev --extra bench`); tests in
  `tests/unit/bench` exercise real AgentDojo pipelines with scripted transports (no network).

## Exact next task
Once `GROQ_API_KEY` exists and `config/providers.yaml` has real limits (not `null`):
1. `make up` (Redis). `make bench ATTACK=none MODEL=groq/llama-3.3-70b-versatile` restricted first to one task:
   `uv run python -m provguard.bench run --model groq/llama-3.3-70b-versatile --redis-url redis://localhost:6379/0 --user-task user_task_1`.
   Check `results/*.json` → `usage` (requests, tokens) and extrapolate the days a 169-run arm needs. Write that
   into `PROGRESS.md` (this is what GATE 1 asks for).
2. Verify Groq accepts our payloads (system role, `seed`, `tool_choice`); adjust `ProvguardLLM` if not and record
   it in ADR-003.
3. Record the smoke cassette: `--smoke --mode record --cassette results/cassettes/smoke.json` (benign and
   `important_instructions`), commit it, make `make bench-smoke` a CI step later.
4. Full banking arms: `none` + `spotlighting_with_delimiting` + `repeat_user_prompt` + `tool_filter`, benign and
   `important_instructions`. `make report`. → GATE 1.
If no key is available: start Phase 2b (`provguard.agent`): planner prompt + JSON plan parsing into
`provguard.core.Plan`, extractor prompt, and a `BasePipelineElement` that runs `PlanRunner` and emits
AgentDojo-format messages (assistant `tool_calls` + tool results) so trace-based checks work (recon §7).

## Open decisions (not yet made)
- OD1 resolved: planner literals are `USER` if verbatim in the prompt, else `PLANNER` (ADR-002 amendment 1).
- OD2–OD4 resolved in ADR-003 (named attack; Codespace chunks first, revisit after one measured arm;
  `transformers_pi_detector` deferred to Phase 3).
- OD5 Phase 2b message emission: how `PlanRunner` records map to AgentDojo `ChatAssistantMessage.tool_calls`
  (one assistant message per executed CallTool, plus a final assistant text from `Respond`).

## Known risks
- Strict-mode banking utility will be structurally low (predicted ≤ ~8/16 tasks auto-allowed). This is expected and
  must be reported, not tuned away.
- Groq free-tier RPD may make a full 169-run arm take several days; the runner must be resumable (Phase 1).
- Our `ProvguardLLM` payload (system role, `seed`, `tool_choice`) is untested against the real Groq endpoint.
- The human has not yet verified any provider's "no payment method" status.

## Things deliberately not done
- No agent code (`provguard.agent`), no CI workflow, no cassette (needs a key), no `docs/RESULTS.md`. No CI workflow yet (Phase 7, but a minimal
  `ci.yml` running `make check` is cheap and could be added any time).
