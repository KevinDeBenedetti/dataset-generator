PYTHONPATH=$(PWD)

.PHONY: help for datasets generator
.DEFAULT_GOAL := help

help: ## Show helper
	@echo "Usage: make <command>"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'

clean: ## Clean cache, datasets, and scrapes
	docker compose down
	cd apps/server && \
		rm -rf .venv uv.lock scraper.log

	@echo "Removing all..."
	@find . -type d -name "pnpm-lock.yaml" -prune -print -exec rm -rf {} +
	@find . -type d -name "node_modules" -prune -print -exec rm -rf {} +
	@find . -type d -name "__pycache__" -prune -print -exec rm -rf {} +
	@find . -type d -name ".pytest_cache" -prune -print -exec rm -rf {} +
	@find . -type d -name ".ruff_cache" -prune -print -exec rm -rf {} +

	cd apps/client && \
		pnpm store prune

lint: setup-server ## Run linting
	@echo "Running linting..."
	cd apps/server && \
		uv run ruff check --fix && \
		uv run ruff format

setup-husky: ## Setup husky git hooks
	@echo "Setting up husky..."
	pnpm install
	chmod +x .husky/pre-commit

setup-client: ## Initialize client
	@echo "Initializing client..."
	cd apps/client && \
	pnpm install

update-client: setup-client ## Upgrade client dependencies
	@echo "Upgrading client dependencies..."
	cd apps/client && \
	pnpm up --latest

lint-client: setup-client ## Run client linting
	@echo "Running client linting..."
	cd apps/client && \
	pnpm lint && \
	pnpm format

setup-server: ## Initialize server
	@echo "Initializing server..."
	cd apps/server && \
	uv venv --clear && \
	source .venv/bin/activate && \
	uv sync

start: clean setup-husky setup-client setup-server ## Start the FastAPI server
	@echo "Starting API server..."
	docker compose up -d
