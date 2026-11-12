# Provenance Guard

A provenance-tracking policy layer for tool-using LLM agents that blocks indirect prompt injection by design:
every value carries the set of sources it came from, and a deterministic policy engine checks those sources
before any side-effecting tool call. Evaluated on [AgentDojo](https://github.com/ethz-spylab/agentdojo).

**Status:** Phase 0 (recon + scaffold) done. No results yet; every number in this repo is `[PENDING]` until it is
produced by `make report` from `results/`.

| | benign utility | utility under attack | targeted ASR |
|---|---|---|---|
| no defense | [PENDING] | [PENDING] | [PENDING] |
| Provenance Guard (strict) | [PENDING] | [PENDING] | [PENDING] |
| Provenance Guard (permissive) | [PENDING] | [PENDING] | [PENDING] |

## Develop
```
make setup     # uv sync + pre-commit install
make check     # ruff + mypy --strict + pytest (coverage gate)
make up        # redis, postgres, qdrant (docker compose, waits for health)
```
Docs: `PLAN.md`, `docs/THREAT_MODEL.md`, `docs/adr/`, `docs/recon/`, `docs/learn/`.
