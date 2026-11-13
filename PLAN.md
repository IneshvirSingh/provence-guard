# PLAN.md — Provenance Guard

Adapted from `docs/Master_Prompt.md` §6 after Phase 0 recon (2026-11-12). Deviations are marked **Δ**.

## Model handover
Claude Fable 5.1 until 2026-11-17, then Claude Opus 5.5. Fable's window is spent on the parts that need the most
careful reasoning: Phase 0, the Phase 2 core design (`docs/design/core.md`), and `provguard.core` with unit +
property tests. The Phase 1 harness comes after, if time remains. `docs/HANDOFF.md` is kept current.

## Phase 0: Recon and scaffold — DONE pending GATE 0 review
Scaffold (uv, ruff, mypy, pytest, pre-commit with gitleaks, Makefile, docker-compose for Redis/Postgres/Qdrant),
`docs/recon/agentdojo.md`, `docs/recon/papers.md`, `docs/THREAT_MODEL.md`, `policies/trust.yaml`, ADR-001, ADR-002,
`config/providers.yaml`. **Δ** self-hosted Langfuse dropped from compose (ADR-001). **Δ** GitHub Models retired
(2026-07-30); second model family = Gemini free tier or Colab-served open model.

## Phase 2a (pulled forward): core design + implementation, no LLM calls — DONE pending mini-GATE 2a review
- `docs/design/core.md`: plan DSL (`CallTool`, `Extract`, `Select`, bounded `ForEach`, `Respond`), provenance
  semantics (per-field labels, union, echo rules), policy language and schema, per-tool policies for the five
  guarded banking tools from tool semantics only, property-test list, known failure modes and limitations.
- `src/provguard/core/`: `provenance.py` (Source, Labeled, labelling of tool outputs from `trust.yaml`),
  `plan.py` (pydantic plan schema + static validation), `policy.py` (loader, engine, Decision with reasons),
  `tests/unit` + `tests/property` (hypothesis). Coverage ≥ 85%.
- Acceptance: property tests prove C1 (no untrusted auto-allow) for arbitrary compositions. → mini-GATE 2a.

## Phase 1: Baselines and evaluation harness — harness DONE; smoke recorded 2026-11-13; full arms pending (quota-chunked)
Quota guard (Redis, limits from `config/providers.yaml`), resumable async runner with sha256 cache and cassette
mode, AgentDojo driver via Python API with Groq-backed `OpenAILLM` (verify `developer` role; verify
`important_instructions` model-name constraint; ADR-003 on run scheduling: Codespace chunks vs GitHub Actions),
banking runs: no defense + every applicable shipped defense under `important_instructions`; metrics with Wilson
CIs; `make report`; ~10-case smoke subset with recorded responses. **Δ** `transformers_pi_detector` baseline needs
torch: run it on Colab/Actions or defer to Phase 3 (decide in ADR-003). → GATE 1.

## Phase 2b: The defense end-to-end — agent code DONE 2026-11-13 (ADR-004); first live run on 1 task; arms pending
Planner + quarantined extractor + policy engine + confirmation handlers (strict/permissive/interactive) inside
one AgentDojo pipeline element; full banking runs both modes; confirmation rate; overhead; `docs/FAILURES.md`;
fallback (argument-provenance matching) if utility collapses. → GATE 2.

## Phase 3: Own detector (data card, dedup + leak check, Colab training, MLflow, ONNX, HF Hub, AgentDojo arm) → GATE 3
## Phase 4: Adaptive attacker (local only), McNemar, budget curves → GATE 4
## Phase 5: RAG + custom docs suite (or documented cut) → GATE 5
## Phase 6: Production service (FastAPI, auth, audit log, abuse controls, demo UI, load test) → GATE 6
## Phase 7: CI/CD, Terraform, Azure for Students, rollback drill, runbook → GATE 7
## Phase 8: Results, write-up, README, interview prep, upstream PR (candidate: `is_task_injectable` bug) → GATE 8
## Phase 9: Stretch (MCP proxy, QLoRA extractor, Slack held-out run, latency work) — only on explicit go

## Scope-cut ladder (unchanged): stretch → custom docs suite → self-hosted Langfuse (**taken**) → live demo →
adaptive budget sweep. Never cut: honest baselines, CIs, quota guard, tests, CI, deployment, failure taxonomy.
