# ADR-001: Stack

Status: accepted (2026-11-12). Supersedes the stack table in `docs/Master_Prompt.md` §4 where they differ.

## Context

Flagship portfolio project, ₹0 budget, 2-core Codespace with a 15–20 GB-month storage quota, one student
maintaining it, every choice must be defensible in an interview. The core research claim (provenance labels +
deterministic policies stop indirect prompt injection) must not depend on any heavy dependency.

## Decisions

| area | decision | alternatives rejected | why |
|---|---|---|---|
| Language/tooling | Python 3.12, `uv` (lockfile, `package = true`), ruff (lint+format), `mypy --strict` on `src/`, pytest + hypothesis, pre-commit (ruff, mypy, gitleaks) | poetry, pip-tools; pyright | uv is fastest and one tool for venv+lock; mypy strict + pydantic plugin catches provenance type errors early |
| Core package | `provguard.core` has **only** `pydantic` and `pyyaml` as dependencies | putting everything in one env | the security argument lives in a module anyone can install and property-test in seconds |
| Benchmark | `agentdojo==0.1.35` as an optional extra `bench`, driven via its Python API (`benchmark_suite_with_injections`) with our own `BasePipelineElement` | forking AgentDojo; the CLI | the CLI only knows `ModelsEnum` providers; Groq is not one. Forking would violate rule 3 |
| LLM access | OpenAI-compatible async client against **Groq free tier** (primary) and **Gemini free tier** (second family); open-weight model on free Colab/Kaggle as fallback. Every provider in `config/providers.yaml` with `requires_payment_method: false` | GitHub Models | **GitHub Models was retired on 2026-07-30** (docs.github.com/en/github-models); removed from the plan |
| Agent runtime | plain asyncio state machine inside one pipeline element for the benchmark; LangGraph only in the product (Phase 6) for interrupts/checkpointing | LangGraph everywhere | the benchmark path must be minimal and deterministic; LangGraph earns its place only where human-in-the-loop interrupts and resumable runs are needed. Re-evaluate in the Phase 6 ADR |
| Cache / limits | Redis (`redis:7.4-alpine`) | sqlite | needed anyway for the product's rate limiter; one store for cache, quota guard, buckets |
| Vector store | Qdrant (`qdrant/qdrant:v1.13.2`) | pgvector | payload filters on `tenant_id`/`trust` are first-class; free cloud tier exists |
| DB | Postgres 16 + SQLAlchemy async + Alembic | sqlite | multi-tenant audit log needs real concurrency; Neon free tier for hosting |
| Observability | OpenTelemetry + structured logs + Prometheus; **Langfuse Cloud free tier**, not self-hosted | self-hosted Langfuse in compose | Langfuse v3 self-hosting needs ClickHouse + MinIO + Redis + Postgres (>1.5 GB of images) which the storage quota cannot afford. This is scope-cut ladder item 3 taken early. `docker-compose.yml` therefore has Redis, Postgres, Qdrant only |
| Detector | small encoder fine-tuned on Colab/Kaggle, exported to ONNX; `torch`/`transformers` in the `ml` extra, never installed in the Codespace | running training locally | 2 cores, no GPU, storage quota |
| Delivery | Docker multi-stage non-root, GitHub Actions, Trivy, pip-audit, gitleaks | – | free for public repos |
| Cloud | Azure for Students, Container Apps scale-to-zero, Terraform, GitHub OIDC | – | no card; keyless deploys. Fallback documented in the master prompt |
| Long runs | decided at Phase 1 (ADR-003): resumable chunks in the Codespace vs GitHub Actions | – | needs measured requests/tokens per run first |

## Consequences

- `make check` runs in well under a minute with the dev group only; the `bench` extra pulls ~200 MB.
- GitHub Models' removal means the "second model family" comes from Gemini's free tier or a Colab-served model;
  the human must copy both consoles' limits into `config/providers.yaml` before any LLM call.
- Self-hosted Langfuse is gone; if Langfuse Cloud's free tier turns out to require a card, OTel + logs only.
- Anything added later must come with its own ADR answering "why this and not the alternative?".
