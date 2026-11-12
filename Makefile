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

bench-smoke: ## [Phase 1] ~10-case smoke benchmark from recorded responses
> @echo "not implemented until Phase 1" && exit 1

bench: ## [Phase 1] make bench SUITE=banking DEFENSE=none ATTACK=important_instructions
> @echo "not implemented until Phase 1 (SUITE=$(SUITE) DEFENSE=$(DEFENSE) ATTACK=$(ATTACK))" && exit 1

report: ## [Phase 1] Generate docs/RESULTS.md from results/*.json
> @echo "not implemented until Phase 1" && exit 1

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
