# HANDOFF.md — for the next model/session

Last updated: 2026-11-13, end of session 4 (Claude Fable 5.1). Fable is available until 2026-11-17; Claude Opus
5.5 continues afterwards. Read `CLAUDE.md`, `PLAN.md`, `PROGRESS.md`, `HUMAN_TODO.md` first.

## State
- Phase 0 done (GATE 0 "go"). Phase 2a done (mini-GATE 2a "go"). Phase 1 harness done and **live-verified**
  on Groq (ADR-003 addendum 1): smoke subset recorded to `results/cassettes/smoke.json`, two smoke result files
  in `results/`, `docs/RESULTS.md` generated. No full arm yet.
- Phase 2b agent code done (ADR-004, `src/provguard/agent/`), tested end to end with scripted LLMs, and run live
  once (`user_task_1`, strict): planner works, answer wrong by design limits (FAILURES F1, F2).
- `make check` green (coverage gate across core/llm/bench/agent). `make check-models` passes against Groq.
- Keys: `GROQ_API_KEY` and `GEMINI_API_KEY` exist as Codespaces secrets. Gemini is disabled in config.
- Quota facts (console + headers): gpt-oss-120b and qwen3.8-27b 30 RPM / 1000 RPD / 8000 TPM / 200k TPD each.
  **TPD is the binding constraint**: ≈3 days per attacked baseline arm (see PROGRESS session 4 projection).

## Exact next task
1. If the session-4 changes are not committed yet: review `git diff -- config/providers.yaml`, then commit all
   (conventional messages per area) and push.
2. Record the guard smoke cassette so CI can replay both modes:
   `uv run python -m provguard.bench run --model groq/openai/gpt-oss-120b --redis-url redis://localhost:6379/0 --defense provguard_strict --smoke --mode record --cassette results/cassettes/smoke.json --force-rerun`
   and the same with `--attack important_instructions`, then `--defense provguard_permissive`. Read every
   failure in `runs/provguard-*/` and append benign ones to `docs/FAILURES.md` (never read injection contents).
3. Full arms, cheapest first, one per Codespace session (`make up` first; runs resume from `runs/`):
   `make bench ATTACK=none DEFENSE=none` → `DEFENSE=provguard_strict` → `DEFENSE=provguard_permissive`
   (≈34k tokens each), then attacked: `make bench ATTACK=important_instructions DEFENSE=none` (≈3 days),
   `provguard_strict`, `provguard_permissive`. `make report` after each. Baseline `spotlighting_with_delimiting`,
   `repeat_user_prompt`, `tool_filter` after that. GATE 1 and GATE 2 can be reviewed together.
4. Planner prompt iteration is allowed only from benign failures in `docs/FAILURES.md`; record each change there.
5. Second family: the same arms with `MODEL=groq/qwen/qwen3.8-27b` (own TPD; can run in a parallel session).

## Open decisions (not yet made)
- OD1 resolved: planner literals are `USER` if verbatim in the prompt, else `PLANNER` (ADR-002 amendment 1).
- OD2–OD4 resolved in ADR-003 (named attack; Codespace chunks first, revisit after one measured arm;
  `transformers_pi_detector` deferred to Phase 3).
- OD5 resolved in ADR-004 §5 (one assistant+tool pair per executed call; plan JSON in a leading assistant
  message; final assistant text last).
- OD6 Planner utility: if strict-mode benign utility lands far below the predicted ≈8/16, decide between a
  bounded re-plan (planner sees only *trusted* fields of outputs) and the §5.8 fallback. Needs the measured arm.

## Known risks
- Strict-mode banking utility will be structurally low (predicted ≤ ~8/16 tasks auto-allowed). This is expected and
  must be reported, not tuned away.
- Groq free-tier RPD may make a full 169-run arm take several days; the runner must be resumable (Phase 1).
- Groq free-tier TPD makes the full matrix ≈2–3 weeks of serial quota; model retirements can strand a config
  (`make check-models` catches it, the arms must then be rerun on a new model and labelled as such).
- gpt-oss-120b reasoning tokens count against quota; `reasoning_effort: low` is set, output quality unmeasured.

## Things deliberately not done
- No CI workflow yet (Phase 7; a minimal `ci.yml` running `make check` + `make bench-smoke` is cheap now that
  the cassette exists). No interactive confirmation handler (Phase 6).
