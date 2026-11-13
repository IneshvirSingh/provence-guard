# HANDOFF.md — for the next model/session

Last updated: 2026-11-13, end of session 5 (Claude Fable 5.2). Fable is available until 2026-11-17; Claude Opus
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
**Blocked on human decision OD7** (strict benign utility 1/5 on the smoke subset; see PROGRESS session 5 and
`docs/FAILURES.md` F3–F6). Do not spend quota on full guard arms before it is answered.
After OD7:
1. Apply the chosen planner changes, rerun the same smoke subset for both modes
   (`--smoke --force-rerun --mode record --cassette results/cassettes/smoke.json`), update the 3-arm table.
2. Human-requested step 4, not started: ADR + GitHub Actions workflow that runs one quota-sized chunk per day,
   resumable, cache persisted between runs (results branch vs actions/cache: pick and justify). Schedule stays
   disabled until the human approves.
3. Then full arms, cheapest first (`make up`; benign none/strict/permissive ≈34k tokens each; attacked ≈3 days
   each for baselines), `make report` after each. Second family: `MODEL=groq/qwen/qwen3.8-27b`.
Note: `make up` (Redis) is needed after every Codespace restart; the Redis cache does not survive it, the
cassette and `runs/` do.

## Open decisions (not yet made)
- OD1 resolved: planner literals are `USER` if verbatim in the prompt, else `PLANNER` (ADR-002 amendment 1).
- OD2–OD4 resolved in ADR-003 (named attack; Codespace chunks first, revisit after one measured arm;
  `transformers_pi_detector` deferred to Phase 3).
- OD5 resolved in ADR-004 §5 (one assistant+tool pair per executed call; plan JSON in a leading assistant
  message; final assistant text last).
- **OD7 (needs the human): how to recover planner utility without weakening isolation.** Candidates, all
  generic: (a) give the planner today's date as a SYSTEM value so `date` arguments need no question (F3, F4);
  (b) reword prompt rule 4 so it asks only when the value exists nowhere, not when the ledger has it (F4);
  (c) fuzzy text matching: route subject matching through `extract` or add a normalised `contains` (F5);
  (d) a bounded second planning round that sees only *trusted* fields (also OD6); (e) accept and report.
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
