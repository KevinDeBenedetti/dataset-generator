# syntax=docker/dockerfile:1

# =============================================================================
# Stage: base
# Base configuration with UV
# =============================================================================
FROM python:3.14-slim AS base

# Pinned by tag and digest (dependabot bumps both); `latest` would change the
# build under us.
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /uvx /bin/

ENV DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# =============================================================================
# Stage: dependencies
# Python packages only — no Chromium/Playwright or other browser stack needed.
# =============================================================================
FROM base AS dependencies

# Copy only dependency files to maximize cache
COPY pyproject.toml uv.lock ./

# Use cache mount to speed up installation.
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

# =============================================================================
# Stage: prod-dependencies
# Runtime packages only, no dev tools. The models run on the OpenAI-compatible
# endpoint: nothing to download into the image.
# =============================================================================
FROM base AS prod-dependencies

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# =============================================================================
# Stage: prod
# What Kubernetes runs — the API (default command) and the job worker
# (`python -m server.worker`), from one image. Non-root, no reload, tini as
# PID 1 so SIGTERM reaches uvicorn / the worker (which drains its runs).
# The root filesystem can be read-only: nothing writes outside /tmp and $HOME.
# =============================================================================
FROM base AS prod

ARG APP_PORT=8000

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && useradd --system --uid 10001 --create-home --home-dir /home/app app

ENV PATH=/app/.venv/bin:$PATH \
    HOME=/home/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_CONCURRENCY=1

COPY --from=prod-dependencies /app/.venv /app/.venv
# The package lives at /app/server (PYTHONPATH=/app); alembic.ini's
# script_location is relative to /app.
COPY ./apps/server ./server

USER 10001
EXPOSE ${APP_PORT}

# Liveness only (no database): readiness is GET /ready, wired in the chart.
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

ENTRYPOINT ["tini", "--"]
# --proxy-headers trusts X-Forwarded-* from FORWARDED_ALLOW_IPS (set it to the
# ingress's address, or rate limits see the proxy's IP for every client).
# Each uvicorn worker loads the ONNX model: keep WEB_CONCURRENCY small.
CMD ["sh", "-c", "exec uvicorn server.main:app --host 0.0.0.0 --port 8000 --proxy-headers --workers ${WEB_CONCURRENCY}"]
