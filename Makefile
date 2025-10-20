
MK_DIR := mk
MK_REPO := https://github.com/KevinDeBenedetti/make-library.git
MK_BRANCH := main
PROJECT_NAME := documentation
STACK := vue fastapi husky
# VUE
VUE_DIR := ./apps/client
JS_PKG_MANAGER := pnpm
VUE_DOCKERFILE := https://raw.githubusercontent.com/KevinDeBenedetti/docker-library/main/vue/Dockerfile
# FASTAPI
FASTAPI_DIR := ./apps/server
PY_PKG_MANAGER := uv
FASTAPI_DOCKERFILE := https://raw.githubusercontent.com/KevinDeBenedetti/docker-library/main/fastapi/Dockerfile
# HUSKY
HUSKY_DIR := ./apps/client
# DOCKER
DOCKER ?= true

MK_FILES := $(addsuffix .mk,$(STACK))
SPARSE_CHECKOUT_FILES := common.mk $(MK_FILES)

.PHONY: help init dockerfiles fix-sparse

help: ## Show helper
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

init: ## Initialize or update the make library
	@echo "==> Checking git sparse-checkout configuration..."
	@git sparse-checkout disable 2>/dev/null || true
	@if [ ! -d $(MK_DIR) ]; then \
		echo "==> Cloning make-library with sparse checkout..."; \
		git clone --no-checkout --depth 1 --branch $(MK_BRANCH) --filter=blob:none $(MK_REPO) $(MK_DIR); \
		cd $(MK_DIR) && \
		git sparse-checkout init --no-cone && \
		echo "common.mk" > .git/info/sparse-checkout && \
		$(foreach file,$(MK_FILES),echo "$(file)" >> .git/info/sparse-checkout &&) true && \
		git checkout $(MK_BRANCH) && \
		rm -rf .git; \
		echo "==> Files added to repository tracking"; \
	else \
		echo "==> Updating make-library..."; \
		rm -rf $(MK_DIR); \
		git clone --no-checkout --depth 1 --branch $(MK_BRANCH) --filter=blob:none $(MK_REPO) $(MK_DIR); \
		cd $(MK_DIR) && \
		git sparse-checkout init --no-cone && \
		echo "common.mk" > .git/info/sparse-checkout && \
		$(foreach file,$(MK_FILES),echo "$(file)" >> .git/info/sparse-checkout &&) true && \
		git checkout $(MK_BRANCH) && \
		rm -rf .git; \
		echo "==> Files updated and added to repository tracking"; \
	fi

dockerfiles: ## Download Dockerfiles from GitHub
	@echo "==> Downloading Dockerfiles..."
	@if [ -n "$(VUE_DOCKERFILE)" ]; then \
		echo "  -> Downloading Vue Dockerfile to $(VUE_DIR)/Dockerfile"; \
		curl -fsSL $(VUE_DOCKERFILE) -o $(VUE_DIR)/Dockerfile; \
	fi
# 	@if [ -n "$(FASTAPI_DOCKERFILE)" ]; then \
# 		echo "  -> Downloading FastAPI Dockerfile to $(FASTAPI_DIR)/Dockerfile"; \
# 		curl -fsSL $(FASTAPI_DOCKERFILE) -o $(FASTAPI_DIR)/Dockerfile; \
# 	fi
	@echo "==> Dockerfiles downloaded successfully"

INCLUDES := $(MK_DIR)/common.mk $(addprefix $(MK_DIR)/,$(MK_FILES))

-include $(INCLUDES)
