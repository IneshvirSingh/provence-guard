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

## Phase 1 + 2b: baselines, harness and the defense end-to-end — code DONE; planner frozen at tag `planner-v1`
Harness (ADR-003), agent (ADR-004 + amendments 1–4), output schemas, protocol (`docs/PROTOCOL.md`), audited
utility. Smoke subset recorded. Benign protocol (3 runs × `none`, `provguard_strict`) in progress, limited
only by the 200k tokens/day quota. No further planner changes until Phase 9 (stop rule, 2026-11-13).

## Next steps, in order (details: `docs/HANDOFF.md` §5)
1. Finish the benign protocol runs (status: `docs/HANDOFF.md` §3); report official and audited utility as measured.
2. ~~ADR-005 + Actions workflow~~ written 2026-11-14 (`.github/workflows/bench-chunk.yml`, manual trigger only,
   state on branch `bench-state`). Waiting on the human: repo secret + first manual run (`HUMAN_TODO.md` §4);
   the schedule stays off until approved.
3. Attacked arms through that workflow, in the order of `config/bench_queue.yaml`: `provguard_strict`,
   `provguard_permissive`, `none`, then the shipped baseline defenses. → GATE 1 and GATE 2 reviewed together.
4. Phase 3. Prep done 2026-11-14: `docs/DATA_CARD.md` (sources, verified licences, leak-check design) and
   `provguard.detector.leakcheck`. Two questions for the human are in the data card §7.

## Phase 3: Own detector (data card **drafted**, dedup + leak check **core built**, Colab training, MLflow, ONNX, HF Hub, AgentDojo arm) → GATE 3
## Phase 4: Adaptive attacker (local only), McNemar, budget curves → GATE 4
## Phase 5: RAG + custom docs suite (or documented cut) → GATE 5
## Phase 6: Production service (FastAPI, auth, audit log, abuse controls, demo UI, load test) → GATE 6
## Phase 7: CI/CD, Terraform, Azure for Students, rollback drill, runbook → GATE 7
## Phase 8: Results, write-up, README, interview prep, upstream issues (`is_task_injectable` bug; `docs/upstream/` draft for banking tasks 5/6) → GATE 8
## Phase 9: Stretch (MCP proxy, QLoRA extractor, Slack held-out run, latency work) — only on explicit go

## Scope-cut ladder (unchanged): stretch → custom docs suite → self-hosted Langfuse (**taken**) → live demo →
adaptive budget sweep. Never cut: honest baselines, CIs, quota guard, tests, CI, deployment, failure taxonomy.
