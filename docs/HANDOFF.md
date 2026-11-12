# HANDOFF.md — for the next model/session

Last updated: 2026-11-12, end of session 2 (Claude Fable 5.1). Fable is available until 2026-11-17; Claude Opus
5.5 continues afterwards. Read `CLAUDE.md`, `PLAN.md`, `PROGRESS.md`, `HUMAN_TODO.md` first.

## State
- Phase 0 complete (GATE 0 passed with "go"). Phase 2a (design + core) complete and pushed;
  **mini-GATE 2a awaiting review** of `docs/design/core.md` and `policies/banking.yaml`.
- `src/provguard/core` is done: see `docs/learn/phase-2a.md` for the module map. 89 unit + 15 property tests,
  99% coverage. Public API in `provguard.core.__init__`.
- `make check` green; compose services healthy; pre-commit (incl. gitleaks) installed.
- No LLM calls have been made. No API keys exist in the Codespace yet.
- AgentDojo 0.1.35 is **not** installed in the project env (it is an extra: `uv sync --extra bench`). Recon used a
  scratch venv; everything learned is in `docs/recon/agentdojo.md`.

## Exact next task
Phase 1 harness (`src/provguard/llm`, `src/provguard/bench`), in this order:
1. `config/providers.yaml` loader + client that refuses providers not listed / `requires_payment_method != false`.
2. Quota guard (Redis token buckets for RPM/RPD/TPM from the yaml; waits, never exceeds; refuses on `null` limits).
3. Async OpenAI-compatible client with sha256(model, messages, tools, temperature, seed) Redis cache, cassette
   mode for CI, usage accounting (requests/tokens per run).
4. AgentDojo driver via the Python API (`docs/recon/agentdojo.md` §2, §7): `OpenAILLM` on a Groq client (verify
   the `developer` role; else a thin custom LLM element), results wrapper writing `results/*.json` with git SHA,
   versions, model, seed, tokens; Wilson CIs; `make bench`, `make bench-smoke`, `make report`.
5. ADR-003: run scheduling (Codespace chunks vs Actions) and the `important_instructions` model-name handling.
Only after that: Phase 2b wires a planner LLM and extractor LLM to `provguard.core.PlanRunner` inside one
`BasePipelineElement` (emit AgentDojo-format assistant messages with `tool_calls` so trace checks work).

## Open decisions (not yet made)
- OD1 resolved: planner literals are `USER` if verbatim in the prompt, else `PLANNER` (ADR-002 amendment 1).
- OD2 Phase 1 attack naming for Groq models (`important_instructions` needs a `MODEL_NAMES` key in the pipeline
  name). Recommendation: register a subclass with the right prose model name under the same attack name and
  record it in results metadata.
- OD3 Where long benchmark runs execute (Codespace chunks vs GitHub Actions) — ADR-003 after measuring tokens.
- OD4 Whether the `transformers_pi_detector` baseline runs at all before Phase 3 (needs torch).

## Known risks
- Strict-mode banking utility will be structurally low (predicted ≤ ~8/16 tasks auto-allowed). This is expected and
  must be reported, not tuned away.
- Groq free-tier RPD may make a full 169-run arm take several days; the runner must be resumable (Phase 1).
- `OpenAILLM` uses `role="developer"`; Groq compatibility unverified.
- The human has not yet verified any provider's "no payment method" status.

## Things deliberately not done
- No Phase 1 code (`provguard.llm`, `provguard.bench`), no agent code (`provguard.agent`). No CI workflow yet (Phase 7, but a minimal
  `ci.yml` running `make check` is cheap and could be added any time).
