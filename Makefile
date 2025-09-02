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
	rm -rf apps/client/node_modules
	rm -rf apps/server/.venv apps/server/uv.lock apps/server/scraper.log

init-client: ## Initialize client
	@echo "Initializing client..."
	cd apps/client && \
	pnpm install

init-server: ## Initialize server
	@echo "Initializing server..."
	cd apps/server && \
	uv venv --clear && \
	source .venv/bin/activate && \
	uv sync

start: clean init-client init-server ## Start the FastAPI server
	@echo "Starting API server..."
	docker compose up -d
