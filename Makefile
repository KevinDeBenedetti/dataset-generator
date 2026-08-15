PYTHONPATH := $(PWD)

.PHONY: help env setup dev dev-local check-docker check-ports down reset logs clean lint lint-server lint-client precommit test test-ci models api-client
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
## Runs in the foreground with `--watch`: container logs stream live with a
## per-service prefix, and images rebuild automatically when dependencies change
## (source is bind-mounted, so edits hot-reload without a rebuild).
## Ctrl-C stops the stack (use `make down` if it was detached elsewhere).
## Run `DEBUG_LOGS=1 make dev` to enable the in-browser dev log console
## (FastAPI + Next.js logs streamed over SSE; toggle it with Ctrl-` in the UI).
dev: env check-docker check-ports
	@set -a; [ -f .env ] && . ./.env 2>/dev/null; set +a; \
	n="$${NEXT_HOST_PORT:-$${NEXT_PORT:-3000}}"; s="$${SERVER_HOST_PORT:-$${SERVER_PORT:-8000}}"; \
	printf '\n  \033[1;36m▶ Building & starting the stack — Ctrl-C stops it\033[0m\n'; \
	printf '    (service URLs are shown below once every service is healthy)\n\n'; \
	( \
	  health() { docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$$1" 2>/dev/null; }; \
	  until [ "$$(health server-fastapi)" = "healthy" ] && [ "$$(health next)" = "healthy" ]; do \
	    sleep 2; \
	  done; \
	  printf '\n  \033[1;32m✓ Dataset Generator — dev services ready\033[0m\n'; \
	  printf '    Next.js    →  http://localhost:%s\n' "$$n"; \
	  printf '    FastAPI    →  http://localhost:%s\n' "$$s"; \
	  printf '    API docs   →  http://localhost:%s/docs\n\n' "$$s"; \
	) & \
	waiter=$$!; \
	trap 'kill $$waiter 2>/dev/null || true' EXIT; \
	COMPOSE_MENU=false docker compose up --build --watch

## Ensure the Docker daemon is reachable, starting Docker Desktop if needed.
check-docker:
	@if docker info >/dev/null 2>&1; then exit 0; fi; \
	printf '  \033[1;33m⚠ Docker daemon not running — starting Docker Desktop...\033[0m\n'; \
	open -a Docker >/dev/null 2>&1 || true; \
	i=0; while [ $$i -lt 60 ] && ! docker info >/dev/null 2>&1; do sleep 1; i=$$((i+1)); done; \
	if ! docker info >/dev/null 2>&1; then \
		printf '  \033[1;31m✗ Docker daemon is not reachable. Start Docker Desktop and retry.\033[0m\n'; \
		exit 1; \
	fi

## Free dev ports (NEXT_HOST_PORT/NEXT_PORT, SERVER_HOST_PORT/SERVER_PORT, POSTGRES_HOST_PORT) if a crashed run left them bound.
## Releases this project's own containers via `compose down`; for anything else it
## diagnoses and aborts (it never kills the Docker daemon to "free" a port).
check-ports:
	@set -a; [ -f .env ] && . ./.env 2>/dev/null; set +a; \
	docker compose down --remove-orphans >/dev/null 2>&1 || true; \
	for p in "$${NEXT_HOST_PORT:-$${NEXT_PORT:-3000}}" "$${SERVER_HOST_PORT:-$${SERVER_PORT:-8000}}" "$${POSTGRES_HOST_PORT:-5452}"; do \
		holder="$$(lsof -nP -iTCP:$$p -sTCP:LISTEN +c0 -F c 2>/dev/null | sed -n 's/^c//p' | head -n1)"; \
		[ -z "$$holder" ] && continue; \
		cname="$$(docker ps --filter "publish=$$p" --format '{{.Names}}' 2>/dev/null | head -n1)"; \
		if [ -n "$$cname" ]; then \
			printf '  \033[1;31m✗ port %s is published by container "%s".\033[0m\n' "$$p" "$$cname"; \
			printf '     Stop it:  docker stop %s   then re-run make dev\n' "$$cname"; \
		elif printf '%s' "$$holder" | grep -qiE 'docker|vpnkit'; then \
			printf '  \033[1;31m✗ port %s is held by the Docker engine (%s) but no container maps it (stale binding).\033[0m\n' "$$p" "$$holder"; \
			printf '     Restart Docker Desktop to clear it, then re-run make dev.\n'; \
		else \
			printf '  \033[1;31m✗ port %s is in use by "%s" — stop that process, then re-run make dev.\033[0m\n' "$$p" "$$holder"; \
		fi; \
		exit 1; \
	done

## Run the FastAPI server locally with hot-reload (no Docker).
dev-local: env
	uv run uvicorn --host 0.0.0.0 $(SERVER_DIR).main:app --reload

## Stop and remove all containers (no-op if the Docker daemon is not running).
down:
	@docker info >/dev/null 2>&1 && docker compose down || true

## Purge persistent volumes (server venv + node_modules) and rebuild.
## Use after a dependency change: `make dev` keeps the volumes, so a stale
## venv would otherwise mask the new lockfile (e.g. an old litellm lingering).
## WARNING: -v also drops postgres_data, qdrant_storage and redis_data — the
## application database (users, refresh tokens, quality rules) is destroyed and
## rebuilt from migrations on the next `make dev`.
reset: check-docker
	docker compose down -v --remove-orphans
	docker compose build
	@printf '  \033[1;32m✓ Volumes purged and images rebuilt — run `make dev`.\033[0m\n'

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
## Needs a reachable Docker daemon: the suite spins up a throwaway Postgres
## (testcontainers). Set TEST_DATABASE_URL to reuse an existing Postgres instead.
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

## Dump the OpenAPI schema straight from the app (no server needed) to openapi.json.
api-schema:
	@PYTHONPATH=$(PWD)/apps uv run python -m server.scripts.dump_openapi openapi.json

## Regenerate the Next.js OpenAPI client (apps/next/api/*.gen.ts).
## Reads the schema dumped by `api-schema` — no running server needed, and the
## exact same input `api-check` uses, so local and CI generation can't diverge.
## The generator runs from an isolated install in apps/next/openapi-codegen:
## @hey-api/openapi-ts needs the TypeScript 5 JS compiler API, which the
## project's typescript@7 (native tsgo) no longer ships — so a pinned TS 5 lives
## there, without downgrading the app.
api-client: api-schema
	@printf '  \033[1;36m▶ Generating the API client from openapi.json\033[0m\n'
	@cd $(NEXT_DIR) && bun install --cwd openapi-codegen && \
	OPENAPI_INPUT="$(PWD)/openapi.json" ./openapi-codegen/node_modules/.bin/openapi-ts
	@rm -f openapi.json
	@printf '  \033[1;32m✓ Client regenerated in apps/next/api/\033[0m\n'

## Fail if the committed API client has drifted from the server's OpenAPI schema.
## Regenerates (same input as `api-client`) and diffs — this is what CI runs.
api-check: api-client
	@if ! git diff --exit-code -- $(NEXT_DIR)/api; then \
		printf '\n  \033[1;31m✗ The committed API client is out of date.\033[0m\n'; \
		printf '     Regenerate it and commit the result:  make api-client\n\n'; \
		exit 1; \
	fi
	@printf '  \033[1;32m✓ API client is in sync with the server schema.\033[0m\n'

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
