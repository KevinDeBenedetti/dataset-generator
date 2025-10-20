MK_DIR := mk
MK_REPO := https://github.com/KevinDeBenedetti/make-library.git
MK_BRANCH := main
PROJECT_NAME := documentation
STACK := vue fastapi husky
# VUE
VUE_DIR := ./apps/client
JS_PKG_MANAGER := pnpm
# FASTAPI
FASTAPI_DIR := ./apps/server
PY_PKG_MANAGER := uv
# HUSKY
HUSKY_DIR := ./apps/client
# DOCKER
DOCKER ?= true

MK_FILES := $(addsuffix .mk,$(STACK))
SPARSE_CHECKOUT_FILES := common.mk $(MK_FILES)

.PHONY: init
init:
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
		cd $(MK_DIR) && \
		git sparse-checkout init --no-cone && \
		echo "common.mk" > .git/info/sparse-checkout && \
		$(foreach file,$(MK_FILES),echo "$(file)" >> .git/info/sparse-checkout &&) true && \
		git fetch origin && \
		git reset --hard origin/$(MK_BRANCH) && \
		rm -rf .git; \
		echo "==> Files updated and added to repository tracking"; \
	fi

INCLUDES := $(MK_DIR)/common.mk $(addprefix $(MK_DIR)/,$(MK_FILES))

-include $(INCLUDES)
