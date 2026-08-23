# Aakar — orchestrates both stacks. `make help` lists targets.
.DEFAULT_GOAL := help
SHELL := /bin/bash

API := services/api
WEB := apps/web

.PHONY: help install codegen codegen-check dev dev-api dev-web test test-api test-web \
        lint typecheck browser up down clean

help: ## List targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

install: ## Install both stacks
	cd $(API) && uv sync --extra dev
	cd $(WEB) && npm install

browser: ## Install the Playwright browser the Phase 3 critic drives (D-009)
	cd $(WEB) && npx playwright install --with-deps chromium

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
