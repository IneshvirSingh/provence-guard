# Provenance Guard. Uses '>' as the recipe prefix so the file is tab-free.
.RECIPEPREFIX = >
.DEFAULT_GOAL := help
SHELL := /bin/bash

UV ?= uv
RUN := $(UV) run

.PHONY: help setup check lint type test up down bench-smoke bench report train-detector export-onnx load-test tf-plan tf-apply

help:
> @grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

setup: ## Install the locked dev environment and git hooks
> $(UV) sync --group dev
> $(RUN) pre-commit install

lint: ## ruff lint + format check
> $(RUN) ruff check src tests
> $(RUN) ruff format --check src tests

type: ## mypy --strict on src/
> $(RUN) mypy

test: ## pytest with coverage gate (>=85% on provguard.core)
> $(RUN) pytest --cov --cov-report=term-missing

check: lint type test ## lint + type + test (the gate)

up: ## Start local Redis, Postgres, Qdrant and wait for health
> docker compose up -d --wait

down: ## Stop local services (keeps volumes)
> docker compose down

SUITE ?= banking
DEFENSE ?= none
ATTACK ?= important_instructions
MODEL ?= groq/llama-3.3-70b-versatile
REDIS_URL ?= redis://localhost:6379/0
CASSETTE ?= results/cassettes/smoke.json

bench-smoke: ## Smoke subset from recorded responses (no key, no network); needs $(CASSETTE) [PENDING]
> @test -f $(CASSETTE) || { echo "no cassette at $(CASSETTE): record one with MODE=record (needs a key)"; exit 1; }
> $(RUN) python -m provguard.bench run --smoke --mode replay --cassette $(CASSETTE) --model $(MODEL) --attack $(ATTACK) --defense $(DEFENSE)

bench: ## make bench SUITE= DEFENSE= ATTACK= MODEL= (live, quota-guarded via $(REDIS_URL))
> $(RUN) python -m provguard.bench run --suite $(SUITE) --defense $(DEFENSE) $(if $(filter none,$(ATTACK)),,--attack $(ATTACK)) --model $(MODEL) --redis-url $(REDIS_URL)

report: ## Generate docs/RESULTS.md from results/*.json
> $(RUN) python -m provguard.bench report

train-detector: ## [Phase 3]
> @echo "not implemented until Phase 3" && exit 1

export-onnx: ## [Phase 3]
> @echo "not implemented until Phase 3" && exit 1

load-test: ## [Phase 6]
> @echo "not implemented until Phase 6" && exit 1

tf-plan: ## [Phase 7]
> @echo "not implemented until Phase 7" && exit 1

tf-apply: ## [Phase 7]
> @echo "not implemented until Phase 7" && exit 1
