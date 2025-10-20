# Default variables if not defined
FASTAPI_DIR ?= .
DOCKER ?= false

validate-fastapi: ## Validate FastAPI environment
	@echo "Validating FastAPI environment..."
	@echo "PY_PKG_MANAGER: $(PY_PKG_MANAGER)"
	@which $(PY_PKG_MANAGER) > /dev/null || (echo "Error: $(PY_PKG_MANAGER) is not installed" && exit 1)
	@echo "✓ FastAPI environment valid"

dev-fastapi: ## Start FastAPI development server
	@echo "Starting FastAPI development server in $(FASTAPI_DIR) with $(PY_PKG_MANAGER)"

	@if [ "$(DOCKER)" = "true" ]; then \
		echo "Note: Make sure to access the dev server via the correct Docker network settings."; \
		docker compose up -d; \
	else \
		if [ -x "$(PY_PKG_MANAGER) uv" ]; then \
			cd $(FASTAPI_DIR) && source .venv/bin/activate && uv sync; \
		else \
			echo "Warning: 'uv' is not installed. Falling back to standard run command."; \
		fi; \
	fi

build-fastapi: ## Build FastAPI application
	@echo "Building FastAPI in $(FASTAPI_DIR) with $(JS_PKG_MANAGER)"
	@if [ "$(DOCKER)" = "true" ]; then \
		echo "Note: Make sure to access the dev server via the correct Docker network settings."; \
		docker compose build; \
	else \
		cd $(FASTAPI_DIR) && $(JS_PKG_MANAGER) install && $(JS_PKG_MANAGER) run build; \
	fi

lint-fastapi: ## Run FastAPI linting
	@echo "Linting FastAPI in $(FASTAPI_DIR)"
	@if [ -x "$(PY_PKG_MANAGER) uv" ]; then \
		cd $(FASTAPI_DIR) && uv run ruff check --fix || echo "Lint command not available"; \
		cd $(FASTAPI_DIR) && uv run ruff format; \
	else \
		echo "Warning: 'uv' is not installed. Skipping Python linting."; \
	fi

clean-fastapi: ## Clean FastAPI artifacts
	@echo "Cleaning FastAPI artifacts..."
	@find $(FASTAPI_DIR) -type d -name ".venv" -prune -print -exec rm -rf {} + 2>/dev/null || true
	@find $(FASTAPI_DIR) -type d -name "__pycache__" -prune -print -exec rm -rf {} + 2>/dev/null || true
	@find $(FASTAPI_DIR) -type d -name ".pytest_cache" -prune -print -exec rm -rf {} + 2>/dev/null || true
	@find $(FASTAPI_DIR) -type d -name ".ruff_cache" -prune -print -exec rm -rf {} + 2>/dev/null || true

	@if [ "$(DOCKER)" = "true" ]; then \
		echo "Note: Make sure to access the dev server via the correct Docker network settings."; \
		docker compose down; \
	fi

upgrade-fastapi: ## Update FastAPI dependencies
	@echo "Updating FastAPI dependencies..."
	cd $(FASTAPI_DIR) && $(JS_PKG_MANAGER) up --latest || $(JS_PKG_MANAGER) update

# Override common targets for FastAPI
validate: validate-fastapi
dev: dev-fastapi
build: build-fastapi
lint: lint-fastapi
clean: clean-fastapi
upgrade: upgrade-fastapi