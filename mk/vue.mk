# Default variables if not defined
VUE_DIR ?= .
DOCKER ?= false

validate-vue: ## Validate Vue environment
	@echo "Validating Vue environment..."
	@echo "JS_PKG_MANAGER: $(JS_PKG_MANAGER)"
	@which $(JS_PKG_MANAGER) > /dev/null || (echo "Error: $(JS_PKG_MANAGER) is not installed" && exit 1)
	@echo "✓ Vue environment valid"

dev-vue: ## Start Vue development server
	@echo "Starting Vue development server in $(VUE_DIR) with $(JS_PKG_MANAGER)"
	@if [ "$(DOCKER)" = "true" ]; then \
		echo "Note: Make sure to access the dev server via the correct Docker network settings."; \
		docker compose up -d; \
	else \
		cd $(VUE_DIR) && $(JS_PKG_MANAGER) install && $(JS_PKG_MANAGER) run dev; \
	fi

build-vue: ## Build Vue application
	@echo "Building Vue in $(VUE_DIR) with $(JS_PKG_MANAGER)"
	cd $(VUE_DIR) && $(JS_PKG_MANAGER) install && $(JS_PKG_MANAGER) run build

lint-vue: ## Run Vue linting
	@echo "Linting Vue in $(VUE_DIR)"
	cd $(VUE_DIR) && $(JS_PKG_MANAGER) run lint || echo "Lint command not available"
	cd $(VUE_DIR) && $(JS_PKG_MANAGER) run format || echo "Format command not available"

clean-vue: ## Clean Vue artifacts
	@echo "Cleaning Vue artifacts..."
	@find $(VUE_DIR) -type d -name "node_modules" -prune -print -exec rm -rf {} + 2>/dev/null || true
	cd $(VUE_DIR) && $(JS_PKG_MANAGER) store prune
	@if [ "$(DOCKER)" = "true" ]; then \
		echo "Note: Make sure to access the dev server via the correct Docker network settings."; \
		docker compose down; \
	fi
upgrade-vue: ## Update Vue dependencies
	@echo "Updating Vue dependencies..."
	cd $(VUE_DIR) && $(JS_PKG_MANAGER) up --latest || $(JS_PKG_MANAGER) update

# Override common targets for Vue
validate: validate-vue
dev: dev-vue
build: build-vue
lint: lint-vue
clean: clean-vue
upgrade: upgrade-vue