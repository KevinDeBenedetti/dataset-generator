# syntax=docker/dockerfile:1

# =============================================================================
# Stage: base
# Base configuration with UV
# =============================================================================
FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# =============================================================================
# Stage: dependencies
# Python packages only. The browser stack lives in the separate crawl4ai
# service, so no Chromium/Playwright is installed here.
# =============================================================================
FROM base AS dependencies

# Copy only dependency files to maximize cache
COPY pyproject.toml uv.lock ./

# Use cache mount to speed up installation
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# =============================================================================
# Stage: dev
# Development environment
# =============================================================================
FROM base AS dev

ARG APP_PORT=8000
ENV PYTHON_ENV=development

# curl for the healthcheck. This layer only depends on `base`, so it stays
# cached across Python dependency and source changes. The apt cache mounts keep
# downloaded packages warm across rebuilds (docker-clean is removed so the cache
# is actually retained).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl

# Resolved virtualenv.
COPY --from=dependencies /app/.venv /app/.venv
COPY pyproject.toml uv.lock ./

# Copy source code
COPY ./apps/server .

EXPOSE ${APP_PORT}

# `uv sync` first so the persisted `.venv` volume (mounted over the image's
# venv in docker-compose) picks up dependency changes — otherwise newly added
# packages stay missing until the volume is manually recreated. It runs against
# the read-only pyproject.toml/uv.lock mounts and is a no-op when already synced.
# Then --reload-dir limits the watcher to the source so it does not watch
# /app/.venv (thousands of files, churned by bytecode writes).
CMD ["sh", "-c", "uv sync --frozen --no-dev && exec uv run --no-sync uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/server"]
