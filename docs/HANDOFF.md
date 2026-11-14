# HANDOFF.md — complete brief for the next model (Claude Opus 5.5 from 2026-11-18)

Last updated: 2026-11-14 19:55 UTC, session 9 (Claude Fable 5.2). **Final brief from Fable.** Read `CLAUDE.md` first (rules), then this file, then
`PLAN.md`, `PROGRESS.md`, `HUMAN_TODO.md`. The human (Inesh) reviews at every GATE; stop and wait there.

## 1. What exists and works
- **Core** (`src/provguard/core`, design in `docs/design/core.md`, ADR-002): provenance labels, plan language
  (`call/select/filter/compute/reduce/extract/foreach/respond`, values `lit | ref | sys`), policy engine,
  `PlanRunner` (single mediation point). Property tests prove C1 (no untrusted value is auto-allowed).
- **LLM layer** (`src/provguard/llm`, ADR-003): ₹0 provider registry, live `/models` check
  (`make check-models`), Redis quota guard, cached client with cassettes, usage split into live tokens and
  tokens originally paid for by cached responses.
- **Benchmark harness** (`src/provguard/bench`): AgentDojo driver, baseline defenses, `make bench`,
  `make protocol`, `make report` → `docs/RESULTS.md`. Smoke cassette: `results/cassettes/smoke.json`.
- **Agent** (`src/provguard/agent`, ADR-004 with amendments 1–4): blind planner, tool-less extractor, AgentDojo
  element; defenses `provguard_strict` and `provguard_permissive`.
- `make check` green (ruff, mypy --strict, pytest, coverage gate over core/llm/bench/agent).

## 2. Frozen: do not change until Phase 9
Git tag **`planner-v1`** freezes `src/provguard/agent/prompts.py`, `policies/schemas/`, `policies/banking.yaml`,
`policies/trust.yaml`. The human's stop rule: no more fix-and-rerun cycles on the planner. New failures are
appended to `docs/FAILURES.md` and **not fixed**. If you find yourself rerunning the same arm a third time for
the same reason, stop and ask the human.

## 3. Measurement protocol (docs/PROTOCOL.md)
- Benign: 3 runs per arm (`none`, `provguard_strict`), full banking suite, seed k-1 for run k:
  `make up && make protocol K=<1|2|3> DEFENSE=<none|provguard_strict>`, then `make report`.
- Report official utility **and** the audited "real completion" column (vacuous tasks 5, 6, 8, 9, 10 excluded
  for every arm; rule in PROTOCOL.md §4; the set is computed by `vacuous_user_tasks` and stored in each file).
- **Status 2026-11-14 19:55 UTC**: done `none` r1, r2 and `provguard_strict` r1, r2. Strict r3 is **partly
  paid for**: it stopped cleanly on the daily quota after 45,417 tokens, and its 18 responses are in the
  durable file cache `.bench-state/protocol/llm-cache.jsonl` (git-ignored, survives a Codespace stop; Redis does
  not). **Left: finish strict r3 (a few thousand tokens) and run `none` r3 (≈48k)**, after 00:00 UTC, with
  exactly these commands (same flags as `make protocol K=3`, but file-backed state instead of Redis):
  ```
  uv run python -m provguard.bench run --suite banking --defense provguard_strict \
    --model groq/openai/gpt-oss-120b --state-dir .bench-state/protocol --seed 2 --label r3 --logdir runs/r3 --force-rerun
  uv run python -m provguard.bench run --suite banking --defense none \
    --model groq/openai/gpt-oss-120b --state-dir .bench-state/protocol --seed 2 --label r3 --logdir runs/r3 --force-rerun
  make report
  ```
  Exit code 75 means "quota stop, rerun later". If `.bench-state/` is gone (new Codespace), the same commands
  still work; strict r3 is then paid again in full (≈50k). The strict r3 results file will show most tokens as
  `cached_*`: that is the part paid on 2026-11-14.
- Then add r3 strict misses to `docs/FAILURES.md` (section "Benign protocol runs"), replace the interim numbers
  in ADR-006 §1, and report the final table to the human. Interim (2 of 3 runs, `docs/RESULTS.md`): none 18/32
  official, 11/22 audited; strict 14/32 official, 4/22 audited.
- **Decided by the human 2026-11-14: the audited column governs and the option-4 trigger is met.** See task 2a.
- After all six files exist: every strict miss gets an F-number in `docs/FAILURES.md` (read
  `runs/r<k>/provguard-strict-*/banking/user_task_*/none/none.json`; never read injection task contents).

## 4. Quota facts that drive scheduling
- `groq/openai/gpt-oss-120b`: 30 RPM, 1000 RPD, 8000 TPM, **200k TPD (binding)**. Our guard uses fixed UTC-day
  windows and raises `QuotaExhausted` with the seconds to wait; rerun the same command afterwards with
  `--force-rerun` (finished cases are cache hits if Redis survived; `make protocol` already passes it).
- Measured cost: benign `none` arm ≈47k tokens; benign strict arm ≈48k; attacked baseline arm ≈540k (≈3 days).
  Guard attacked arms are far cheaper: the planner prompt does not depend on the injection, so the 9 injection
  variants of a user task share one planner call (extractor calls differ).
- `make up` after every Codespace restart. Redis (cache + quota counters) does not survive a restart; `runs/`
  and cassettes do. `qwen/qwen3.8-27b` has its own 200k TPD and is the second model family.

## 5. Exact next tasks, in order
1. **Finish the benign protocol** (section 3) if any `r<k>` file is missing. Report the table from
   `docs/RESULTS.md` to the human as is, good or bad. → this closes the benign part of GATE 1/2.
2. **ADR-005 + GitHub Actions workflow: written 2026-11-14, never run.** `docs/adr/ADR-005-*.md`,
   `.github/workflows/bench-chunk.yml` (`workflow_dispatch` only), `config/bench_queue.yaml`,
   `python -m provguard.bench run-queue`, file-backed state (`provguard.llm.filestore`) on branch `bench-state`.
   Waiting on the human (`HUMAN_TODO.md` §4): Actions secret `GROQ_API_KEY`, first manual run. After the first
   run: fix whatever breaks, write the ADR addendum, pull results with
   `git fetch origin bench-state && git checkout origin/bench-state -- results/ && make report`.
   **Schedule: approved by the human for 00:30 UTC, but only after one successful manual run** (exit 0 or 75 and
   a pushed `bench-state`). Then uncomment the two `schedule:` lines in the workflow (cron `30 0 * * *`), show
   the diff, commit. Remove the schedule when the queue is complete.
   **Hard rule: on any day a chunk runs (every day once the schedule is on), the Codespace must not use
   `gpt-oss-120b`.** The chunk takes the whole 200k daily quota and the two quota counters do not see each
   other. Codespace live work on those days uses `qwen/qwen3.8-27b` or waits. So finish the benign protocol
   (task 1) **before** the first manual chunk, or on a day without one.
2a. **ADR-006 (accepted 2026-11-14, nothing built): planner-v2 = one bounded second planning round over a
   trusted view.** `docs/adr/ADR-006-planner-v2-trusted-view-replanning.md`. Build order: its §6.
   - **§5 is frozen**, including decision rule 5.5: v2 ships only if (a) it gains ≥ 6 of 33 audited task-runs
     over v1 on banking and reaches half of undefended, (b) targeted ASR is no higher than v1 on banking and
     Slack, (c) Slack audited utility is no worse than v1. Changes only by dated addendum; the margin in (a) was
     set by Fable and the human may replace it **before** v2 development starts.
   - Development: banking benign only, at most two full development runs, then tag `planner-v2`; a third
     needs the human. v2 banking numbers are in-sample; generalisation claims rest on Slack only.
   - Slack: frozen v1 and frozen v2 (plus `none`), once each, side by side, after v2 is final. Slack trust
     entries, policies and schemas are written from tool signatures and docstrings only and tagged
     `slack-eval-v1` before the first Slack request. **Workspace and travel remain unseen; do not touch them.**
   - v1 (`planner-v1`) stays frozen; its results are the first reported result. v2 is a new code path with new
     defense names and does not modify v1.
3. **Attacked arms** through that workflow, cheapest and most informative first: `provguard_strict`, then
   `provguard_permissive`, then `none` (`important_instructions`, banking). Then baselines
   `spotlighting_with_delimiting`, `repeat_user_prompt`, `tool_filter`. Report targeted ASR and utility under
   attack with Wilson CIs, confirmation rate, and how many plans reached a guarded call. An ASR of zero from a
   guard that rarely acts is weak evidence: always report it next to "requests reaching a guarded call".
   The baseline is non-deterministic at temperature 0; ask the human whether attacked arms also need repeats
   before spending ≈3 days of quota per extra baseline run. → GATE 1 and GATE 2 together.
4. **Phase 3** (own detector; master prompt §6). Prep done: `docs/DATA_CARD.md` (five sources, licences
   verified live 2026-11-14, exclusions, leak-check design; human decisions recorded: Dolly CC BY-SA 3.0
   accepted with attribution in §8 and no raw data committed, LLMail cap and seed pre-registered in §4a and
   not to be changed after the first training run) and
   `src/provguard/detector/leakcheck.py` with tests (233 AgentDojo reference fragments indexed; reports carry
   hashes only). Next: detector ADR, build script (dedup → leak check → group splits) writing
   `results/detector_data.json` and `results/leak_check.json`, Colab notebook, MLflow, ONNX, Hugging Face Hub,
   AgentDojo arm. The Prompt Guard models in `config/providers.yaml` (`kind: classifier`) are the
   off-the-shelf baseline. Never train on AgentDojo strings. torch is never installed in the Codespace.
5. Later phases unchanged in `PLAN.md`.

## 6. Open decisions
- OD6 / option 4: resolved; ADR-006 accepted, human decisions in its §7.
- OD8: repeats for attacked arms (see task 3).
- OD9: where `today` should come from in deployment (currently environment calendar, else process clock;
  ADR-004 amendment 3). Fine for the benchmark; revisit in Phase 6.

## 7. Known issues and honest caveats
- AgentDojo banking: 5 of 16 user tasks pass for an agent that does nothing (PROTOCOL.md §4).
  Draft upstream issue for tasks 5 and 6: `docs/upstream/agentdojo-banking-presatisfied-utility.md` (the human
  files it). Second upstream candidate: `TaskSuite.check()` injectability bug (`docs/recon/agentdojo.md`).
- Smoke result files `results/*smoke*.json` predate `planner-v1` (older prompt). They are kept as history; the
  smoke cassette therefore replays the old guard prompts only for the `none` arms reliably. Re-record the guard
  smoke entries once (`--smoke --mode record --cassette results/cassettes/smoke.json --force-rerun`) before
  wiring `make bench-smoke` into CI.
- Groq quirks: rejects `messages[].name`; 403 for urllib's default User-Agent; JSON mode can return HTTP 400
  "Failed to generate JSON" (handled, fails closed); reasoning tokens count against quota.
- No CI workflow yet; no interactive confirmation handler (Phase 6); Gemini disabled.
- `HUMAN_TODO.md` 1.6 (Groq data-use terms into `docs/COSTS.md`) is still open.

## 8. Rules that are easy to break
Never read `default_suites/*/injection_tasks.py` goal or security bodies. Never write model IDs from memory.
No number without a results file (`[PENDING]` otherwise). Show the human provider-config diffs before committing
them. Commit in small conventional chunks and push at the end of every session; no force-push, no PRs.
