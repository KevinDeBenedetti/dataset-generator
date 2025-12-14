PYTHONPATH=$(PWD)

.PHONY: help for datasets generator
.DEFAULT_GOAL := help clean lint dev

# --------------------------------------
# HELPER
# --------------------------------------
help: ## Show helper
	@echo "Usage: make <command>"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'


# --------------------------------------
# CLEAN
# --------------------------------------

clean:  ## Clean cache, datasets, and scrapes
	@echo "Cleaning up..."
	docker compose down

	@echo "Removing all..."
	@find . -type f -name "bun.lock" -prune -print -exec rm -rf {} +
	@find . -type f -name "pnpm-lock.yaml" -prune -print -exec rm -rf {} +
	@find . -type d -name "node_modules" -prune -print -exec rm -rf {} +
	@find . -type d -name "__pycache__" -prune -print -exec rm -rf {} +
	@find . -type d -name ".pytest_cache" -prune -print -exec rm -rf {} +
	@find . -type d -name ".ruff_cache" -prune -print -exec rm -rf {} +
	@find . -type d -name ".venv" -prune -print -exec rm -rf {} +
	@find . -type f -name "uv.lock" -prune -print -exec rm -rf {} +
	@find . -type f -name "*.log" -prune -print -exec rm -rf {} +

rmi: clean
	@echo "Removing dangling images..."
	docker rmi datasets-next datasets-server datasets-vue || true

# --------------------------------------
# LINT
# --------------------------------------

lint:  ## Run linting
	@echo "Server linting..."
	uv run ruff check --fix && \
	uv run ruff format

	@echo "Client linting..."
	cd client && \
		bun lint && \
		bun format


# --------------------------------------
# SETUP
# --------------------------------------
setup: ## Initialize client
	@echo "Initializing..."
	cd ./apps/vue && bun install
	cd ./apps/next && bun install

	@echo "Initializing server..."
	uv venv --clear && \
	source .venv/bin/activate && \
	uv sync

update-client: setup ## Upgrade client dependencies
	@echo "Upgrading client dependencies..."
	cd client && \
	bun up --latest

dev: clean setup ## Start the FastAPI server
	@echo "Starting API server..."
	docker compose up -d

dev-local: clean setup ## Start the FastAPI server without Docker
	@echo "Starting API server..."
	uv run uvicorn --host 0.0.0.0 server.main:app --reload
# 	cd server && \
# 		uv run uvicorn --host 0.0.0.0 main:app --reload

install:
	@echo "Installing dependencies..."
	cd server && PYTHONPATH=$(PWD)/server uv sync --all-groups --dev

test: install
	echo "Running tests..."
	cp .env.example .env
	cd server && PYTHONPATH=$(PWD)/server uv run pytest -s -v tests/ --cov=api --cov-report=term-missing
	rm .env

up-backend-local: ## Start the FastAPI server without Docker
	@echo "Starting API server..."
	cp .env.example server/.env
	cd server && \
		uv run uvicorn --host 0.0.0.0 main:app --reload
	rm server/.env

