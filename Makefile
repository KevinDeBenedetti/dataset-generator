PYTHONPATH=$(PWD)

.PHONY: help for datasets generator
.DEFAULT_GOAL := help

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

rmi:
	@echo "Removing dangling images..."
	docker rmi datasets-next datasets-server datasets-vue || true

# --------------------------------------
# BUILD OPTIMIZATION
# --------------------------------------
build-cache: ## Build with BuildKit cache for faster rebuilds
	@echo "Building with cache optimization..."
	COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker compose build

rebuild: clean rmi build-cache ## Clean rebuild with optimizations
	@echo "Clean rebuild complete"

start: ## Start services (skip build if images exist)
	@echo "Starting services..."
	docker compose up -d

stop: ## Stop services
	@echo "Stopping services..."
	docker compose down

check-docker: ## Check Docker optimization setup
	@echo "Checking Docker setup..."
	./scripts/check-docker-setup.sh

benchmark: ## Benchmark Docker build performance
	@echo "Running Docker build benchmark..."
	cp .env.example scripts/.env
	./scripts/benchmark-docker.sh
	rm scripts/.env

# --------------------------------------
# LINT
# --------------------------------------
lint-server: ## Run server linting
	@echo "Server linting..."
	uv run ruff check --fix
	uv run ruff format
	uv run ty check

lint-client: ## Run client linting
	@echo "Client linting..."
	cd ./apps/vue && \
		bun lint --fix
	cd ./apps/next && \
		bun lint --fix

lint: lint-server lint-client  ## Run linting

precommit:  ## Run pre-commit hooks on all files
	@echo "Running pre-commit hooks..."
	uv run prek run --all-files

precommit-update:  ## Update pre-commit hooks
	@echo "Updating pre-commit hooks..."
	uv run prek auto-update

# --------------------------------------
# SETUP
# --------------------------------------
setup: ## Initialize client
	@echo "Initializing server..."
	uv venv --clear && \
	source .venv/bin/activate && \
	uv sync

	@echo "Initializing..."
	cd ./apps/vue && bun install
	cd ./apps/next && bun install


update-client: setup ## Upgrade client dependencies
	@echo "Upgrading client dependencies..."
	cd apps/vue && \
	bun update --latest
	cd apps/next && \
	bun update --latest

dev: clean rmi setup ## Start the FastAPI server
	@echo "Starting API server..."
	docker compose up -d


dev-local: clean setup ## Start the FastAPI server without Docker
	@echo "Starting API server..."
	uv run uvicorn --host 0.0.0.0 server.main:app --reload


install:
	@echo "Installing dependencies..."
	uv sync --all-groups --dev


up-backend-local: ## Start the FastAPI server without Docker
	@echo "Starting API server..."
	cp .env.example apps/server/.env
	cd apps/server && \
		uv run uvicorn --host 0.0.0.0 main:app --reload
	rm server/.env


# --------------------------------------
# TEST
# --------------------------------------
test: install
	echo "Running tests..."
	uv run pytest -s -v apps/server/tests/ --cov=apps/server --cov-config=.coveragerc --cov-report=term-missing --cov-report=html
