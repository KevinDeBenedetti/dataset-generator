PYTHONPATH=$(PWD)

.PHONY: help for datasets generator
.DEFAULT_GOAL := help clean lint dev

help: ## Show helper
	@echo "Usage: make <command>"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'

clean: ## Clean cache, datasets, and scrapes
	@echo "Cleaning up..."
	docker compose -f docker/docker-compose.yml down

	@echo "Removing all..."
	@find . -type f -name "pnpm-lock.yaml" -prune -print -exec rm -rf {} +
	@find . -type d -name "node_modules" -prune -print -exec rm -rf {} +
	@find . -type d -name "__pycache__" -prune -print -exec rm -rf {} +
	@find . -type d -name ".pytest_cache" -prune -print -exec rm -rf {} +
	@find . -type d -name ".ruff_cache" -prune -print -exec rm -rf {} +

	@echo "Server cleaning..."
	cd apps/server && \
		rm -rf .venv uv.lock scraper.log

	@echo "Client cleaning..."
	cd apps/client && \
		pnpm store prune

lint:  ## Run linting
	@echo "Server linting..."
	cd apps/server && \
		uv run ruff check --fix && \
		uv run ruff format

	@echo "Client linting..."
	cd apps/client && \
		pnpm lint && \
		pnpm format

husky: ## Setup husky git hooks
	@echo "Setting up husky..."
	cd apps/client && pnpm install
	chmod +x .husky/pre-commit

setup: ## Initialize client
	@echo "Initializing client..."
	cd apps/client && \
	pnpm install

	@echo "Initializing server..."
	cd apps/server && \
	uv venv --clear && \
	source .venv/bin/activate && \
	uv sync

update-client: setup ## Upgrade client dependencies
	@echo "Upgrading client dependencies..."
	cd apps/client && \
	pnpm up --latest

dev: clean husky setup ## Start the FastAPI server
	@echo "Starting API server..."
	docker compose -f docker/docker-compose.yml up -d

install:
	@echo "Installing dependencies..."
	cd apps/server && PYTHONPATH=$(PWD)/apps/server uv sync --all-groups --dev

test: install
	echo "Running tests..."
	cp .env.example .env
	cd apps/server && PYTHONPATH=$(PWD)/apps/server uv run pytest -s -v tests/ --cov=api --cov-report=term-missing
	rm .env

up-backend-local: ## Start the FastAPI server without Docker
	@echo "Starting API server..."
	cp .env.example apps/server/.env
	cd apps/server && \
		uv run uvicorn --host 0.0.0.0 --port 5000 main:app --reload

	rm apps/server/.env

rmi: clean
	@echo "Removing dangling images..."
	docker rmi datasets-client datasets-server || true