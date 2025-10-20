.PHONY: help validate dev build test lint clean

help: ## Show helper
	@echo "Project: $(PROJECT_NAME)"
	@echo "Stack: $(STACK)"
	@echo ""
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":"; prev=""} \
		{ \
			file = $$1; \
			gsub(/^.*\//, "", file); \
			if (file != prev && prev != "") print ""; \
			prev = file; \
			sub(/^[^:]*:/, ""); \
			split($$0, arr, ":.*?## "); \
			printf "  \033[36m%-25s\033[0m %s\n", arr[1], arr[2]; \
		}'

validate: ## Validate environment
	@echo "Validating environment..."
	@echo "PROJECT_NAME: $(PROJECT_NAME)"
	@echo "STACK: $(STACK)"

dev: validate ## Start development server
	@echo "Starting development server for project $(PROJECT_NAME) with stack $(STACK)"

build: validate ## Build the project
	@echo "Building project $(PROJECT_NAME) with stack $(STACK)"

test: validate ## Run tests
	@echo "Running tests for $(PROJECT_NAME)"

lint: validate ## Run linting
	@echo "Running linting for $(PROJECT_NAME)"

clean: validate ## Clean artifacts
	@echo "Cleaning artifacts for $(PROJECT_NAME)"
