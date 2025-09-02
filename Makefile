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
	rm -rf scraper.log
	rm -rf apps/server/.venv apps/server/uv.lock

dev: ## Start the FastAPI server
	@echo "Starting API server..."
	uv sync
	uv run fastapi dev

start: clean ## Start the FastAPI server
	@echo "Starting API server..."
	cd apps/server && \
	uv venv --clear && \
	source .venv/bin/activate && \
	uv sync
	docker compose up -d
# 	uv run -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000