# ADR-003: Benchmark harness — LLM element, attack naming, scheduling of long runs

Status: accepted (2026-11-12). Verified against agentdojo==0.1.35 and Groq's OpenAI-compatibility notes
(console.groq.com/docs/openai, read 2026-11-12).

## Context
AgentDojo's own `OpenAILLM` (a) sends the system prompt as `role="developer"`, (b) sets `messages[].name` on
every tool-result message, and (c) is a plain `openai.OpenAI` wrapper with its own retries. Groq documents that
`messages[].name` returns HTTP 400 and that `temperature=0` becomes `1e-8`. The `important_instructions`
attack needs the pipeline name to contain a key of `agentdojo.models.MODEL_NAMES`. A full banking arm is 169
agent runs, each several LLM requests, and Groq's free tier has a daily request cap we do not yet know.

## Decisions
1. **Own LLM element** (`provguard.bench.llm_element.ProvguardLLM`): message conversion mirrors AgentDojo's
   but uses `role="system"` and no `name`; it calls `provguard.llm.LLMClient`, which is quota-guarded, cached,
   and provider-agnostic. Baseline pipelines are rebuilt in `provguard.bench.pipelines.build_pipeline` as an exact
   mirror of `AgentPipeline.from_config` (same elements, same prompts), including `tool_filter` on our client.
2. **Synchronous client, threads for parallelism.** AgentDojo pipelines are synchronous, so the client is too.
   Redis counters are atomic, so several suites/arms can run in threads or processes sharing one quota guard.
   (The master prompt said "async runner"; the asynchrony lives at the runner level, not in the client.)
3. **Quota guard before any call**: fixed per-minute and per-day windows for requests and tokens in Redis, with
   token estimates settled upward after each response and never refunded. Null limits refuse to run. Waits up to
   90 s; longer waits raise `QuotaExhausted` so a daily cap stops the run cleanly and the next day resumes it.
4. **Resumability = AgentDojo per-case logs + exact cache + cassettes.** AgentDojo already skips cases present in
   `runs/`. The cache key is sha256(model, messages, tools, temperature, seed); reruns make zero calls. `record`
   mode writes a cassette JSON so CI runs the smoke subset in `replay` mode with no key and no network.
5. **Attack naming**: `provguard.bench.attacks` registers the *same* `important_instructions` template under
   the same name with the prose model name derived from our pipeline name (`llama` → "Llama", `gpt-oss` →
   "GPT", `gemini` → "AI model developed by Google"). The prose name is recorded in every result file.
6. **Where long runs execute: in the Codespace, chunked by the daily quota**, not GitHub Actions, for now.
   Reason: the quota guard and cache need Redis, and Actions minutes are free but a run that waits on a daily cap
   would idle a runner. Revisit after the first measured arm (requests and tokens per run are written into
   `results/*.json`). If one arm needs more than ~3 Codespace sessions, move to an Actions workflow with an
   Upstash Redis.
7. **`transformers_pi_detector` baseline is deferred to Phase 3** (needs torch; runs on Colab with the same
   cassette mechanism, or in the Codespace only if the storage quota allows a CPU torch install).

## Alternatives rejected
Forking AgentDojo's `OpenAILLM` (rule 3 spirit, and we would still bypass the quota guard); an async client
with `asyncio.to_thread` around AgentDojo (adds complexity, no benefit while the pipeline is sync); naming the
pipeline `local` to satisfy the attack (changes the attack text to "Local model", weaker and misleading).

## Consequences
- The first real run is blocked only on `HUMAN_TODO.md` items 1–2 (keys and console limits).
- Baseline numbers are comparable to the paper's defenses but not to its models.
- `results/cassettes/smoke.json` is `[PENDING]` until recorded; `make bench-smoke` fails clearly until then.
