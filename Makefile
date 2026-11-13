# Provenance Guard. Uses '>' as the recipe prefix so the file is tab-free.
.RECIPEPREFIX = >
.DEFAULT_GOAL := help
SHELL := /bin/bash

UV ?= uv
RUN := $(UV) run

.PHONY: help setup check lint type test up down check-models bench-smoke bench protocol report train-detector export-onnx load-test tf-plan tf-apply

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
MODEL ?= groq/openai/gpt-oss-120b
REDIS_URL ?= redis://localhost:6379/0
CASSETTE ?= results/cassettes/smoke.json

bench-smoke: ## Smoke subset from recorded responses (no key, no network); needs $(CASSETTE) [PENDING]
> @test -f $(CASSETTE) || { echo "no cassette at $(CASSETTE): record one with MODE=record (needs a key)"; exit 1; }
> $(RUN) python -m provguard.bench run --smoke --mode replay --cassette $(CASSETTE) --model $(MODEL) --attack $(ATTACK) --defense $(DEFENSE)

bench: ## make bench SUITE= DEFENSE= ATTACK= MODEL= (live, quota-guarded via $(REDIS_URL))
> $(RUN) python -m provguard.bench run --suite $(SUITE) --defense $(DEFENSE) $(if $(filter none,$(ATTACK)),,--attack $(ATTACK)) --model $(MODEL) --redis-url $(REDIS_URL)

K ?= 1
protocol: ## One protocol run (docs/PROTOCOL.md): make protocol K=1|2|3 DEFENSE=none|provguard_strict
> $(RUN) python -m provguard.bench run --suite $(SUITE) --defense $(DEFENSE) --model $(MODEL) --redis-url $(REDIS_URL) --seed $$(( $(K) - 1 )) --label r$(K) --logdir runs/r$(K) --force-rerun

report: ## Generate docs/RESULTS.md from results/*.json
> $(RUN) python -m provguard.bench report

check-models: ## Verify config/providers.yaml model IDs against each enabled provider's live /models
> $(RUN) python -m provguard.bench check-models

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
