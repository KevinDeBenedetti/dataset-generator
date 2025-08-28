PYTHONPATH=$(PWD)

.PHONY: help for datasets generator
.DEFAULT_GOAL := help

help: ## Show helper
	@echo "Usage: make <command>"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'

clean: ## Clean cache, datasets, and scrapes
	rm -rf cache/ datasets/ scrapes/ scraper.log

start: ## Start generating datasets
	@echo "Start generating datasets..."
	uv sync
	uv run main.py