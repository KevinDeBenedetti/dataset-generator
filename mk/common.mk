.PHONY: help validate dev build test lint clean

validate: ## Validate environment
	@echo "Validating environment..."
	@echo "STACK: $(STACK)"

dev: validate ## Start development server
	@echo "Starting development server with stack $(STACK)"

build: validate ## Build the project
	@echo "Building project with stack $(STACK)"

test: validate ## Run tests
	@echo "Running tests for $(STACK)"

lint: validate ## Run linting
	@echo "Running linting for $(STACK)"

clean: validate ## Clean artifacts
	@echo "Cleaning artifacts for $(STACK)"
