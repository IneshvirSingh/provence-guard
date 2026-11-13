# HANDOFF.md — for the next model/session

Last updated: 2026-11-13, end of session 6 (Claude Fable 5.2). Fable is available until 2026-11-17; Claude Opus
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
State after session 6: OD7 items 1–3 are in (ADR-004 amendment 3). Full benign banking arm measured:
none 7/16, provguard_strict 7/16 (PROGRESS session 6; every strict miss is F-numbered in `docs/FAILURES.md`).
Waiting for the human's read of that result. Likely next, in order:
1. Generic planner/extractor fixes from FAILURES: optional extraction fields (F8, four tasks), one worked
   example of "extract id then filter" in the fictional domain (F5), `select`+`reduce path` clarity (F9).
   Rerun the full benign strict arm; planner calls for unchanged prompts are cache hits only if Redis survived.
2. Rerun the smoke subset for both modes (the committed smoke files predate amendment 3), then
   provguard_permissive benign full arm.
3. Human-requested step 4, not started: ADR + scheduled GitHub Actions workflow (one quota chunk per day,
   resumable, cache persisted; schedule disabled until approved).
4. Attacked arms (≈3 days of TPD per baseline arm). Baseline is non-deterministic at temperature 0: decide on
   repeats (k=3?) before spending the quota.
5. Phase 8 upstream candidates: `is_task_injectable` bug; banking user_task_5 utility passes with no action.
Operational: `make up` after every Codespace restart (Redis cache and quota counters are lost; cassette and
`runs/` survive). Use `--force-rerun` when usage and guard statistics must cover every case.

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
