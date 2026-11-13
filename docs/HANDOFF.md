# HANDOFF.md — complete brief for the next model (Claude Opus 5.5 from 2026-11-18)

Last updated: 2026-11-13, session 7 (Claude Fable 5.2). Read `CLAUDE.md` first (rules), then this file, then
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
- Status of the protocol runs: see `PROGRESS.md` (latest session) and `ls results/*__r*.json`. Any run missing
  there is still to be executed with the command above; nothing else about it may change.
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
2. **ADR-005 + scheduled GitHub Actions workflow for the attacked arms** (human request; not started):
   - ADR first. Decide and justify how state persists between daily runs: a `results` branch (auditable,
     survives cache eviction, but commits AgentDojo logs that contain injection strings) versus `actions/cache`
     (simple, but evicted after 7 days idle and capped at 10 GB). Things the ADR must cover: Redis as a service
     container vs a file-backed cache (a JSON/SQLite `CacheStore` restored from the persisted state is enough;
     the quota guard can use `MemoryStore` per job because each job is one day's chunk); how the job stops
     cleanly on `QuotaExhausted` and still uploads partial state; secrets via repository secret `GROQ_API_KEY`
     (never echoed; gitleaks in the workflow); `make check-models` as the first step; concurrency group so two
     chunks never overlap; one chunk = one arm resumed, sized under 200k tokens.
   - Workflow file with `workflow_dispatch` only. **Do not add the `schedule:` trigger until the human
     approves.** The repo is public, so Actions minutes are free.
3. **Attacked arms** through that workflow, cheapest and most informative first: `provguard_strict`, then
   `provguard_permissive`, then `none` (`important_instructions`, banking). Then baselines
   `spotlighting_with_delimiting`, `repeat_user_prompt`, `tool_filter`. Report targeted ASR and utility under
   attack with Wilson CIs, confirmation rate, and how many plans reached a guarded call. An ASR of zero from a
   guard that rarely acts is weak evidence: always report it next to "requests reaching a guarded call".
   The baseline is non-deterministic at temperature 0; ask the human whether attacked arms also need repeats
   before spending ≈3 days of quota per extra baseline run. → GATE 1 and GATE 2 together.
4. **Phase 3** (own detector; master prompt §6): data card, dedup and leak check, Colab training, MLflow, ONNX,
   Hugging Face Hub, AgentDojo arm. The Prompt Guard models in `config/providers.yaml` (`kind: classifier`)
   are the off-the-shelf baseline. Never train on AgentDojo strings. torch is never installed in the Codespace.
5. Later phases unchanged in `PLAN.md`.

## 6. Open decisions
- OD6 / option 4 (deferred by the human): a bounded second planning round that sees only trusted fields, to
  address tasks that need judgement on data (F6). Only to be proposed as an ADR draft if the protocol shows
  strict utility below half of undefended; not to be built without a "go".
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
