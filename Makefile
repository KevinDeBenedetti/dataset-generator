PYTHONPATH := $(PWD)

.PHONY: help env setup dev dev-local down logs clean lint lint-server lint-client precommit test test-ci models
.DEFAULT_GOAL := help

SERVER_DIR := apps/server
NEXT_DIR   := apps/next

## Show this help message.
help:
	@echo ""
	@echo "  Usage: make <target>"
	@echo ""
	@awk '/^## /{if (!desc) desc=substr($$0,4); next} /^[a-zA-Z_-]+:/{split($$0,a,":"); if(desc) printf "  \033[36m%-14s\033[0m %s\n", a[1], desc; desc=""; next} {desc=""}' $(MAKEFILE_LIST)
	@echo ""

## Create .env from .env.example if it does not exist.
env:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

## Install all dependencies: Python server (uv) and the Next.js client (bun).
setup:
	uv venv --clear && uv sync
	cd $(NEXT_DIR) && bun install

## Start the full stack with Docker (FastAPI + Next.js), building images if needed.
dev: env
	@set -a; [ -f .env ] && . ./.env 2>/dev/null; set +a; \
	n="$${NEXT_HOST_PORT:-8080}"; s="$${SERVER_HOST_PORT:-8000}"; \
	printf '\n  \033[1;36mDataset Generator — dev services\033[0m\n'; \
	printf '    Next.js    →  http://localhost:%s\n' "$$n"; \
	printf '    FastAPI    →  http://localhost:%s\n' "$$s"; \
	printf '    API docs   →  http://localhost:%s/docs\n\n' "$$s"
	docker compose up -d --build

## Run the FastAPI server locally with hot-reload (no Docker).
dev-local: env
	uv run uvicorn --host 0.0.0.0 $(SERVER_DIR).main:app --reload

## Stop and remove all containers.
down:
	docker compose down

## Stream logs from all containers.
logs:
	docker compose logs -f

## Remove containers, caches, lockfiles and virtualenvs.
clean: down
	@find . -type d -name "node_modules" -prune -print -exec rm -rf {} +
	@find . -type d -name "__pycache__" -prune -print -exec rm -rf {} +
	@find . -type d -name ".pytest_cache" -prune -print -exec rm -rf {} +
	@find . -type d -name ".ruff_cache" -prune -print -exec rm -rf {} +
	@find . -type d -name ".venv" -prune -print -exec rm -rf {} +

## Lint and format the Python server (ruff + ty).
lint-server:
	uv run ruff check --fix
	uv run ruff format
	uv run ty check

## Lint and fix the Next.js client (bun).
lint-client:
	cd $(NEXT_DIR) && bun lint --fix

## Run all linters (server + client).
lint: lint-server lint-client

## Run pre-commit hooks on all files.
precommit:
	uv run prek run --all-files

## Run the test suite with coverage (HTML report).
test:
	uv run pytest -s -v $(SERVER_DIR)/tests/ \
		--cov=$(SERVER_DIR) \
		--cov-config=.coveragerc \
		--cov-report=term-missing \
		--cov-report=html

## Run tests for CI with XML coverage and a 70% threshold.
test-ci:
	uv run pytest -s -v $(SERVER_DIR)/tests/ \
		--cov=$(SERVER_DIR) \
		--cov-config=.coveragerc \
		--cov-report=xml \
		--cov-report=term-missing \
		--cov-fail-under=70

## List models from the configured OpenAI-compatible provider (reads .env).
models:
	@set -a; . ./.env 2>/dev/null; set +a; \
	if [ -z "$$OPENAI_BASE_URL" ] || [ -z "$$OPENAI_API_KEY" ]; then \
		echo "⚠ OPENAI_BASE_URL or OPENAI_API_KEY is unset in .env"; \
		exit 1; \
	fi; \
	printf '\033[1;36m▶ Models from %s\033[0m\n' "$$OPENAI_BASE_URL"; \
	url="$${OPENAI_BASE_URL%/}/models"; \
	if resp="$$(curl -fsS "$$url" -H "Authorization: Bearer $$OPENAI_API_KEY")"; then \
		echo "$$resp" | jq -r '.data[]?.id' 2>/dev/null | sed 's/^/  • /'; \
	else \
		echo "  ⚠ request failed ($$url)"; \
	fi
