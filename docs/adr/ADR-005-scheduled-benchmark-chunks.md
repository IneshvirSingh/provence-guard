# ADR-005: Resumable benchmark chunks on GitHub Actions, state on a `bench-state` branch

Status: proposed (2026-11-14). The workflow exists with a manual trigger only; **the daily schedule is not
enabled and needs the human's approval** (section 7). Supersedes ADR-003 decision 6 ("long runs execute in the
Codespace"). Verified on 2026-11-14: action versions and commit SHAs via the GitHub API
(`actions/checkout` v7.0.1, `astral-sh/setup-uv` v10.3.3, `actions/upload-artifact` v7.0.2), gitleaks v8.30.1
checksum from its release page. The workflow has not run yet; first-run findings go in an addendum.

## Context
- The binding limit is Groq's 200k tokens/day for `openai/gpt-oss-120b`. One attacked baseline arm on banking
  costs about 540k tokens (measured, `results/`), so every attacked arm spans several UTC days.
- In the Codespace a multi-day arm needs the human to start the Codespace daily (free hours are limited), and
  Redis, which holds the cache and quota counters, is wiped on every Codespace stop. On 2026-11-13/14 a stop
  lost a partly paid-for run.
- The repo is public, so GitHub-hosted runner minutes are free. ₹0 holds.

## Decision
1. **One workflow, `.github/workflows/bench-chunk.yml`; one run = one day's chunk.** It runs
   `python -m provguard.bench run-queue`, which walks `config/bench_queue.yaml` in order, skips arms whose
   results file exists, and stops on `QuotaExhausted` with exit code 75. The workflow treats 0 (queue done) and
   75 (quota stop) as success and anything else as failure.
2. **Resume = exact-response cache, not per-case logs.** An interrupted arm restarts from its first case; every
   request it already paid for is a cache hit (key = sha256 of the full request including seed), so only missing
   cases cost tokens. The results file is written only when an arm completes; its usage block separates live
   tokens from tokens paid on earlier days (`cached_*`).
3. **File-backed state instead of Redis** (`provguard.llm.filestore`): `FileCache` is an append-only JSONL
   file, flushed per response, tolerant of a torn last line. `FileCounterStore` persists the quota windows, so
   two chunks on the same UTC day share one budget; a corrupt counter file stops the run rather than starting
   from zero. Selected with `--state-dir`; mutually exclusive with `--redis-url`. One process per job, so no
   atomicity is needed. Redis stays for the Codespace and the product.
4. **State persists on an orphan branch `bench-state`** (`cache/llm-cache.jsonl`, `cache/quota.json`,
   `results/*.json`), one appended commit per chunk, never force-pushed. The workflow never writes to `main`.
   Results reach `main` by a reviewed human/agent commit:
   `git fetch origin bench-state && git checkout origin/bench-state -- results/ && make report`.
5. **AgentDojo per-case logs are not committed.** They are uploaded as a 30-day workflow artifact and can be
   regenerated at zero token cost by replaying the arm against the cache (`run ... --state-dir <copy of cache>`).
6. **Safety**: secret only as repository secret `GROQ_API_KEY`, passed as env to two steps, never echoed;
   triggers are `workflow_dispatch` (and later `schedule`) only, so fork pull requests cannot reach it;
   `permissions: contents: write` and nothing else; actions pinned by commit SHA; gitleaks (checksum-pinned
   binary) scans the state directory and **the push is skipped if the scan fails**; `check-models` runs before
   any LLM call; a `concurrency` group prevents two chunks overlapping.
7. **Schedule (not enabled)**: proposed `cron: "17 0 * * *"`, shortly after the 00:00 UTC reset. Consequences
   the human should accept before approving: (a) the chunk uses the whole day's gpt-oss-120b quota, so live
   Codespace work on that model the same day will hit 429s (the Codespace's Redis counters do not see Actions
   usage); use `qwen/qwen3.8-27b` in the Codespace or pause the schedule; (b) GitHub disables schedules after 60
   days without repo activity; (c) the schedule must be removed when the queue is complete (a finished queue
   exits in seconds, so forgetting is cheap but noisy).

## Alternatives rejected
- **`actions/cache`** for the state: entries are immutable per key (needs a new key every run plus
  `restore-keys`), evicted after 7 days without access and under a repo-wide size cap, invisible in the repo and
  not fetchable from the Codespace. A lost cache means re-paying days of quota. The branch is auditable (every
  number traces to a committed file), shared with the Codespace, and survives idle weeks.
- **Committing state to `main`**: bot commits would interleave with reviewed history and trigger CI.
- **Redis service container**: empty at every job start, so it would still need dump/restore to a file.
- **Hosted Redis (Upstash free tier)**, as ADR-003 suggested: another account, another secret and another free
  tier to verify, for something a file does.
- **Workflow artifacts as state**: need cross-run download logic and expire.

## Consequences and limits
- The branch grows by one blob of the cache per chunk (git delta-compresses appended lines). Responses are
  small next to prompts; if `llm-cache.jsonl` passes ~20 MB, shard it per arm. The branch can be deleted after
  results are merged and the final cache is archived as a release asset.
- The cache holds model responses, which can echo text from AgentDojo's public injection strings. Nothing
  secret; do not read it for task content (rule 3).
- A provider 429 that our counters did not predict fails the job (red) after 4 retries; state is still saved.
- Attacked arms are not repeated yet (open decision OD8); the queue supports `seed`/`label` per arm when they are.
- Queue order and scope are code-reviewed data (`config/bench_queue.yaml`), tested in
  `tests/unit/bench/test_cli_queue.py`. `transformers_pi_detector` is excluded (needs torch; Phase 3).
