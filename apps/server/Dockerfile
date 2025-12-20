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
# Install dependencies with cache
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

# Install curl for healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies from the previous stage
COPY --from=dependencies /app/.venv /app/.venv
COPY pyproject.toml uv.lock ./

# Copy source code
COPY ./apps/server .

EXPOSE ${APP_PORT}

# Import from server.main
CMD ["uv", "run", "--no-sync", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
