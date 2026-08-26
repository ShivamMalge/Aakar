# Aakar — orchestrates both stacks. `make help` lists targets.
.DEFAULT_GOAL := help
SHELL := /bin/bash

API := services/api
WEB := apps/web

.PHONY: help install codegen codegen-check dev dev-api dev-web test test-api test-web \
        lint typecheck browser shots up down clean

help: ## List targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

install: ## Install both stacks
	cd $(API) && uv sync --extra dev
	cd $(WEB) && npm install

browser: ## Install the Playwright browser the Phase 3 critic drives (D-009)
	# D-009 drives Playwright from services/api, so the browser is installed by the
	# stack that launches it. Node and Python share one browser cache.
	cd $(API) && uv run playwright install chromium

GOLDEN := human_eye earth_layers animal_cell

shots: ## Phase 1 gate captures — needs the web app running (1.6, D-009)
	cd $(API) && uv run python -m aakar.render.screenshots $(GOLDEN) \
	  --out ../../evidence/phase1 --angle 0 --angle 1
	cd $(API) && uv run python -m aakar.render.screenshots earth_layers human_eye \
	  --out ../../evidence/phase1 --angle 0 --cutaway on
	cd $(API) && uv run python -m aakar.render.screenshots earth_layers \
	  --out ../../evidence/phase1 --angle 0 --explode 1
	# Both G-10 modes on the one topic with real nesting — this pair is the evidence
	# behind D-017, so it is reproducible rather than a one-off capture.
	cd $(API) && uv run python -m aakar.render.screenshots animal_cell \
	  --out ../../evidence/phase1 --angle 0 --explode 0.6 --explode-mode top-level
	cd $(API) && uv run python -m aakar.render.screenshots animal_cell \
	  --out ../../evidence/phase1 --angle 0 --explode 0.6 --explode-mode per-part
	# The 40-part stress fixture (specs/stress), at the schema's cap and depth 6.
	cd $(API) && uv run python -m aakar.render.screenshots neuron \
	  --out ../../evidence/phase1 --angle 0 --angle 1
	cd $(API) && uv run python -m aakar.render.screenshots neuron \
	  --out ../../evidence/phase1 --angle 0 --cutaway on
	cd $(API) && uv run python -m aakar.render.screenshots neuron \
	  --out ../../evidence/phase1 --angle 0 --explode 0.6
	cd $(API) && uv run python -m aakar.render.probe $(GOLDEN) neuron \
	  --out ../../evidence/phase1/interaction-transcript.txt

codegen: ## Regenerate zod + pydantic from scenespec.schema.json (D7)
	./packages/scenespec/codegen.sh

GENERATED := $(WEB)/src/scenespec/generated.ts $(API)/aakar/scenespec/generated.py

codegen-check: codegen ## Fail if generated types are stale (the D7 drift test)
	@for f in $(GENERATED); do \
	  git ls-files --error-unmatch $$f >/dev/null 2>&1 || \
	    { echo "DRIFT CHECK INVALID: $$f is untracked, so git diff can never see it."; exit 1; }; \
	done
	@git diff --exit-code -- $(GENERATED) \
	  || { echo ""; \
	       echo "DRIFT: scenespec.schema.json changed but generated types were not regenerated."; \
	       echo "Run \`make codegen\` and commit the result."; \
	       exit 1; }
	@echo "no drift: generated types match the schema"

dev: ## Run both stacks (api :8000, web :3000)
	@$(MAKE) -j2 dev-api dev-web

dev-api:
	cd $(API) && uv run uvicorn aakar.app:app --reload --port 8000

dev-web:
	cd $(WEB) && npm run dev

test: test-api test-web ## Run both suites

test-api: ## pytest (replay mode — no key, no spend)
	cd $(API) && AAKAR_PROVIDER_MODE=replay uv run pytest -q

test-web: ## vitest
	cd $(WEB) && npm run test

lint: ## ruff + eslint
	cd $(API) && uv run ruff check . && uv run ruff format --check .
	cd $(WEB) && npm run lint

typecheck: ## mypy (strict) + tsc
	cd $(API) && uv run mypy
	cd $(WEB) && npm run typecheck

up: ## Start Qdrant
	docker compose up -d

down: ## Stop Qdrant
	docker compose down

clean:
	rm -rf $(WEB)/.next $(WEB)/node_modules/.cache $(API)/.pytest_cache $(API)/.mypy_cache $(API)/.ruff_cache
