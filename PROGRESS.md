# PROGRESS.md

## Session 1 — 2026-11-12 (Claude Fable 5.1)

**Phase 0: complete, awaiting GATE 0 review.**

Built:
- Scaffold: `pyproject.toml` (uv, pinned deps, extras `bench`/`ml`, dev group), `uv.lock`, ruff, mypy --strict
  (pydantic plugin), pytest + coverage gate (85% on `provguard.core`), `.pre-commit-config.yaml` (ruff, mypy,
  gitleaks v8.30.1 — builds from Go, ~2 min first run), `Makefile` (all required targets; later phases stub with
  exit 1), `docker-compose.yml` (Redis 7.4, Postgres 16, Qdrant 1.13.2 with healthchecks), `.env.example`,
  `config/providers.yaml`, `policies/trust.yaml`.
- Docs: `docs/recon/agentdojo.md` (from installed 0.1.35 source), `docs/recon/papers.md`, `docs/THREAT_MODEL.md`,
  `docs/adr/ADR-001-stack.md`, `docs/adr/ADR-002-provenance-model.md`, `docs/learn/phase-0.md`, `docs/COSTS.md`,
  `docs/HANDOFF.md`, `CLAUDE.md`, `PLAN.md`, `HUMAN_TODO.md`.

Measured: nothing yet (no LLM calls made). All numbers in docs are quoted from the papers and labelled as such.

Verified:
- `make check` green (ruff, mypy strict, 2 tests, coverage 100% of the 1-statement core package).
- `docker compose up -d --wait`: redis, postgres, qdrant all healthy; then `down`.
- `pre-commit run --all-files` passes including gitleaks.
- AgentDojo facts verified by executing the installed package: banking v1.2.2 = 16 user / 9 injection tasks,
  11 tools, 4 injection vectors; `security=True` ⇔ injection goal achieved (ran `suite.check()`).

Broke / surprises:
- GitHub Models retired 2026-07-30 → dropped (ADR-001). Second model family now Gemini free tier / Colab.
- Self-hosted Langfuse too heavy for the storage quota → scope-cut item 3 taken early (ADR-001).
- AgentDojo `TaskSuite.check()` says every banking task is "not injectable" (upstream bug in
  `is_task_injectable`; attacks unaffected). Logged as the Phase 8 upstream-contribution candidate.
- `important_instructions` attack raises unless the pipeline name contains a known model-name key; and
  `OpenAILLM` sends system prompts as `role="developer"`. Both go into the Phase 1 ADR.

Recommend next: human reviews GATE 0 (THREAT_MODEL, trust.yaml, ADR-002 especially the per-field trust and
"no control-flow taint" decisions), fills `HUMAN_TODO.md` items 1–2. Next session writes `docs/design/core.md`.

## Session 2 — 2026-11-12 (Claude Fable 5.1)

**Phase 2a (design + core): complete, awaiting mini-GATE 2a review.**

Built:
- `docs/design/core.md`: plan DSL, provenance semantics (incl. two ADR-002 refinements: `PLANNER` source and
  selection taint), policy language, banking policies from tool semantics, predicted strict-mode ceiling (≈8/16,
  a prediction, not a result), property-test list, failure modes.
- `src/provguard/core/`: `provenance.py`, `trust.py`, `plan.py`, `extraction.py`, `policy.py`, `runner.py`
  (≈660 statements). `policies/banking.yaml`.
- Tests: 89 unit tests (`tests/unit/`) incl. end-to-end plan runs on a fake bank (refund auto-allowed; bill
  payment CONFIRM → strict denies / permissive pays; DENY stops; extraction fails closed; foreach; grounding),
  15 hypothesis property tests (`tests/property/`) incl. C1 at the policy level and end-to-end through the runner.

Measured: coverage 99% on `provguard.core` (gate 85%). No LLM calls, no benchmark numbers.

Broke / surprises:
- Hypothesis health check on oversized random trees → inputs shrunk.
- Numeric grounding missed negative/exponent literals → regex fixed, property test caught it.
- Push-down semantics make a record's trusted source appear alongside the field's untrusted one in explanations
  (harmless: untrusted dominates; documented in `tests/unit/test_trust.py`).

Recommend next: review `docs/design/core.md` §3–§4 (policy language and the banking allow-lists) and the two
ADR-002 refinements. Then Phase 1 harness (quota guard, runner, Groq adapter) or Phase 2b agent, per `PLAN.md`.

## Session 3 — 2026-11-12 (Claude Fable 5.1)

**Phase 1 harness: code complete; no benchmark run yet (no API key, no console limits). GATE 1 cannot be
reached until the human completes `HUMAN_TODO.md` items 1–2.**

Built:
- `src/provguard/llm/`: `providers.py` (₹0 registry; refuses unlisted / unverified providers), `quota.py`
  (Redis or memory fixed-window guard for RPM/RPD/TPM/TPD; waits, or raises `QuotaExhausted` at a daily cap),
  `client.py` (sync OpenAI-compatible client: sha256 cache, `live|record|replay` cassettes, jittered retries,
  usage summary).
- `src/provguard/bench/`: `llm_element.py` (`ProvguardLLM`, `ToolFilter`), `pipelines.py` (none + 4 shipped
  defenses mirrored from `AgentPipeline.from_config`), `attacks.py` (named `important_instructions`),
  `runner.py` (`run_arm` → `results/<arm>.json` with git SHA, versions, usage, Wilson CIs), `stats.py`,
  `report.py` (`make report` → `docs/RESULTS.md`), CLI `python -m provguard.bench`.
- `docs/adr/ADR-003-benchmark-harness.md`, `docs/learn/phase-1.md`, Makefile `bench`, `bench-smoke`, `report`.
- `pyproject.toml`: extras `llm` (openai, redis) and `bench` (agentdojo 0.1.35); dev adds fakeredis.

Verified (no network): scripted-transport tests drive real AgentDojo banking pipelines end to end
(`user_task_1` solved; `tool_filter` prunes tools; rerun from `runs/` makes zero calls; attack arm writes a
results file with the prose model name). `make check` green; coverage gate still ≥ 85% across core/llm/bench.

Measured: nothing. `results/` has no arm files; `docs/RESULTS.md` is not generated until one exists.

Broke / surprises:
- Groq rejects `messages[].name` (HTTP 400) and AgentDojo's `OpenAILLM` sets it → own LLM element (ADR-003).
- agentdojo ships no `py.typed`; mypy strict needed `disallow_subclassing_any = false` for `provguard.bench.*`.
- The smoke cassette (`results/cassettes/smoke.json`) cannot be recorded without a key → `[PENDING]`.

Recommend next: human does `HUMAN_TODO.md` 1–2, then `make up && make bench ATTACK=none` for the benign
baseline on 1–2 user tasks first (check tokens/requests per run), then record the smoke cassette, then the
full arms. Alternatively, start Phase 2b (planner/extractor prompts + AgentDojo adapter around
`provguard.core.PlanRunner`), which also needs a key to test for real.

## Session 4 — 2026-11-13 (Claude Fable 5.1)

**Keys arrived. First live calls. Phase 1 smoke recorded. Phase 2b agent code complete; first live guard run.**

Built:
- `config/providers.yaml` rewritten from the live Groq `/models` list (Llama models retired for free accounts
  2026-08-16): `openai/gpt-oss-120b` primary (`reasoning_effort: low`, no parallel tool calls),
  `qwen/qwen3.8-27b` second family, `llama-prompt-guard-2-{86m,22m}` as `kind: classifier`; Gemini disabled.
  Limits from the console; RPD/TPM confirmed from `x-ratelimit-*` headers (`limits_source`).
- `ProviderRegistry.check_models` + `make check-models`: the configured IDs are compared with the live `/models`
  before every live/record run. Groq returns 403 to urllib's default User-Agent (fixed with `provguard/0.1`).
- `LLMClient`: `request_defaults` merged into every payload (and the cache key); `response_format`; `record` mode
  now also writes cache hits to the cassette. Partial/smoke runs write `results/<arm>__<label>.json`.
- Core: `reduce` op (`sum|count|min|max`, optional `path`) — design §1 updated.
- `src/provguard/agent/` (ADR-004): planner, extractor, `ProvenanceGuard` AgentDojo element,
  `build_guard_pipeline`; `provguard_strict` / `provguard_permissive` in `DEFENSES` and the CLI.
- Docs: ADR-003 addendum 1, ADR-004, `docs/learn/phase-2b.md`, `docs/FAILURES.md`, `docs/RESULTS.md`
  (generated), COSTS/HUMAN_TODO updated.

Measured (all from `results/*.json`, gpt-oss-120b, banking, git 4c7a6da+working tree):
- Benign smoke (5 user tasks, defense none): utility 4/5; 10 live + 2 cached calls; 10,642 tokens.
- Attacked smoke (5 user tasks × 2 injection tasks, `important_instructions`): utility under attack 4/10,
  targeted ASR 7/10; 29 live + 10 cached calls; 42,296 tokens. Both injection tasks solvable as user tasks.
- Cassette `results/cassettes/smoke.json`: 41 recorded responses; `make bench-smoke` now works offline.
- Guard, `user_task_1`, strict, live: 1 planner call, 1,766 tokens, utility False (F1 then F2 in FAILURES.md).

Projection (arithmetic from the smoke numbers; not a result):
- Per benign run ≈2.4 calls, ≈2.1k tokens → full benign arm (16 tasks) ≈38 calls, ≈34k tokens: fits one day.
- Per attacked run ≈3.3 calls, ≈3.5k billed tokens → full attacked arm (144 cases + 9 injection-as-user) ≈500
  calls, ≈540k tokens → **≈3 days of the 200k TPD per attacked baseline arm**; RPD (1000) is not binding; TPM
  (8000) forces ≥70 min wall time per arm. Guard arms: ≈1 planner call (≈1.7k) + ≤1 extractor call per case →
  ≈2 days per attacked arm. GATE 1 (4 baselines) + GATE 2 (2 guard modes), attacked + benign ≈ 15–17 days of
  gpt-oss-120b quota if run serially; qwen has its own per-model TPD and can run the second family in parallel.

Broke / surprises:
- gpt-oss-120b returns a `reasoning` field and counts reasoning tokens in `completion_tokens` (quota!).
- Prompt Guard reports `total_tokens: 0`; our estimate overcounts (harmless).
- First planner plan reduced records instead of amounts (F1); second run included an incoming transfer (F2).
- Hypothesis found `compute("div", 1, 2.2e-311)` → inf → `ProvenanceError`; the property test now accepts it.

Recommend next: review the `config/providers.yaml` diff (asked for before commit), then commit; then
`docs/HANDOFF.md` §Exact next task.

## Session 5 — 2026-11-13 (Claude Fable 5.2)

**Early utility signal: strict benign utility is 1/5 on the smoke subset. Stopped for human review (as asked).**

Built: output schemas for the planner (`policies/schemas/banking.yaml`, ADR-004 amendment 1); `--no-schemas`
ablation; guard statistics in results (`guard`: confirmations, statuses); provider JSON failures fail closed;
two hypothesis properties for `reduce` (exact union of list, record and selected-field sources; count on
arbitrary lists). Session-4 work committed in six conventional commits after a clean gitleaks + key scan.

Measured (banking smoke subset: user tasks 1,3,4,7,14; injection tasks 0,1; gpt-oss-120b; `results/*smoke*`):

| arm | benign utility | utility under attack | targeted ASR | requests hitting CONFIRM |
|---|---|---|---|---|
| none | 4/5 | 4/10 | 7/10 | n/a |
| provguard_strict | 1/5 | 2/10 | 0/10 | 0/5 benign, 0/12 attacked |
| provguard_permissive | 1/5 | 2/10 | 0/10 | 0/5 benign, 0/12 attacked |
| provguard_strict, no schemas | 0/5 | not run | not run | 0/5 |

Tokens: guard benign 5 live planner calls = 10,576 tokens (≈2.1k per uncached case; the committed strict
benign file is a later fully cached rerun and shows 0). Attacked guard arms were almost entirely cache hits
(the planner prompt does not depend on the injection): 2 live calls, 4,763 tokens. Baseline: 10,642 benign,
42,296 attacked.

Reading (n is tiny; intervals in `docs/RESULTS.md`):
- Strict and permissive are identical because no plan ever reached a CONFIRM: the planner stops and asks
  instead of acting (F3, F4), mismatches free text (F5) or cannot branch (F6). The policy engine was not the
  cause of any benign failure here.
- ASR 0/10 is therefore weak evidence: the guard blocked nothing because almost nothing was attempted.
  Attacked statuses: 10 ok, 1 denied, 1 error. The security claim needs arms where the guard actually acts.

Recommend next: human decision OD7 (HANDOFF) before any further quota is spent. Step 4 (scheduled Actions
workflow + ADR) not started.

## Session 6 — 2026-11-13 (Claude Fable 5.2)

**OD7 items 1–3 implemented; full benign banking arm measured for none and provguard_strict.**

Built: `{"sys": "today"}` SYSTEM value (env clock if present, else process clock; banking has no clock,
verified); prompt rules 2 and 4 reworded; extractor-based matching documented + property test; cached-token
accounting in results (`cached_*_tokens`); `guard.requests_reaching_guarded_call`; bad `respond` templates fail
closed (crash found by the full run). ADR-004 amendment 3.

Measured (16 user tasks, benign, gpt-oss-120b; files `results/banking__{none,provguard_strict}__none__*.json`):
- none: 7/16 = 43.8% [23.1, 66.8]; 45 live calls, 46,703 tokens.
- provguard_strict: 7/16 = 43.8% [23.1, 66.8]; 17,177 live + 29,191 served-from-cache tokens (rerun after the
  crash fix). Plans reaching a guarded tool call: 3/16; 2 hit CONFIRM (denied in strict), 1 auto-allowed
  (task 4 refund). Statuses: 6 ok, 2 denied, 7 error, 1 planner failed.
- Equal by AgentDojo's metric, but not equal in substance: see `docs/FAILURES.md` (4 of the strict passes need no
  action or are scored true despite a denial; substantive completions strict 3, baseline 5).
- Baseline non-determinism: tasks 1, 3, 14 passed in the smoke run and failed here with the same settings
  (temperature 0, seed 0). One run per arm is not enough for this model; plan for repeats or report it.

Not done: smoke files in `results/*smoke*` predate amendment 3 (old planner prompt); attacked arms; step 4
(Actions workflow). Option-4 ADR draft not written: the trigger (strict below half of undefended) did not fire.

