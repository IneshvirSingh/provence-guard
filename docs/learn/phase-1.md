# Learn: Phase 1 — baselines and the evaluation harness (code done, runs pending keys)

## What was built
- `provguard.llm.providers`: the ₹0 rule as code. `ProviderRegistry.resolve("groq/llama-3.3-70b-versatile")`
  refuses any provider missing from `config/providers.yaml` or without `requires_payment_method: false`.
- `provguard.llm.quota`: `QuotaGuard` with RPM/RPD/TPM/TPD fixed windows in Redis (`RedisStore`) or memory
  (`MemoryStore` for tests). Waits for the next minute; raises `QuotaExhausted` on a daily cap.
- `provguard.llm.client`: `LLMClient.chat()` with sha256 cache, `live | record | replay` cassette modes, jittered
  retries on transient errors, and a `UsageSummary` (requests, cache hits, tokens, retries, wall time).
- `provguard.bench`: `ProvguardLLM` element, `build_pipeline` for `none` and the four shipped defenses, the named
  `important_instructions` attack, `run_arm` writing `results/<arm>.json` with git SHA, versions, usage and
  Wilson-CI metrics, `make report` → `docs/RESULTS.md`, and a CLI (`python -m provguard.bench run|report`).
- Tests: scripted transports drive real AgentDojo pipelines on the banking suite without network (e.g.
  `user_task_1` solved end to end; `tool_filter` prunes tools; a rerun makes zero calls).

## Concepts
1. **Rate-limit windows.** Fixed windows keyed by `floor(now / 60)` are simple, atomic with `INCRBY`, and
   conservative (a burst at a boundary can use two windows' worth; we accept that since the provider also limits).
2. **Exact-response caching** makes experiments reproducible and reruns free, but only if every input that
   changes the output is in the key (model, messages, tools, temperature, seed).
3. **Cassettes** are the benchmark's unit tests: recorded responses replayed in CI, so a code change that breaks
   a pipeline fails a test without spending quota.
4. **Wilson interval** for proportions: better coverage than the normal approximation at small n and near 0/1,
   which is exactly where ASR values sit.
5. **Pessimistic error accounting.** AgentDojo records provider errors as `utility=False, security=True`; our
   report inherits that, so flaky networks make a defense look worse, never better.

## Five interview questions
**Q1. Why didn't you use AgentDojo's OpenAI client with Groq's base URL?** Groq rejects `messages[].name` (400)
and AgentDojo sets it on every tool message (`openai_llm.py::_message_to_openai`); also our quota guard and cache
would be bypassed. `ProvguardLLM` mirrors the conversion without `name` (ADR-003).

**Q2. How do you guarantee you never exceed a free-tier limit?** `QuotaGuard.acquire` checks all four windows
before each request, increments atomically, and settles tokens upward after the response. Limits come from the
provider console, copied by a human; `null` refuses to run (`tests/unit/llm/test_quota.py`).

**Q3. How is a run resumable across days?** Three layers: AgentDojo skips cases already in `runs/`, the client
returns cached responses for identical requests, and `QuotaExhausted` stops cleanly at the daily cap.

**Q4. Why re-register `important_instructions`?** The shipped attack derives the victim's prose name from the
pipeline name and raises for unknown models. We keep the template and supply the name; the name used is in the
results metadata so the choice is auditable.

**Q5. What is measured per arm?** Benign utility, utility under attack, targeted ASR (with Wilson CIs and n),
whether each injection task is solvable by the pipeline at all, requests, cache hits, tokens, wall time, git SHA
and package versions (`provguard.bench.runner.ArmResult`).
