HUSKY_DIR ?= .

dev-husky: ## Set up Husky git hooks
	@echo "Setting up Husky in $(HUSKY_DIR) with $(JS_PKG_MANAGER)"
	cd $(HUSKY_DIR) && $(JS_PKG_MANAGER) install

dev: dev-husky