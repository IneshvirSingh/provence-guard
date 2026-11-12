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
