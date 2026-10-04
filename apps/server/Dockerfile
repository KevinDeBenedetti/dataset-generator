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
# Python packages only — no Chromium/Playwright or other browser stack needed.
# =============================================================================
FROM base AS dependencies

# Copy only dependency files to maximize cache
COPY pyproject.toml uv.lock ./

# Use cache mount to speed up installation. The `jobs` group (Claude Agent SDK)
# is included so the dashboard's Sync jobs page can run the Q&A job in-process.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group jobs

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
CMD ["sh", "-c", "uv sync --frozen --no-dev --group jobs && exec uv run --no-sync uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/server"]

# =============================================================================
# Stage: prod-dependencies
# Runtime packages only (no dev tools, no Claude SDK: the Claude subscription
# provider never runs on a deployed server) plus the local embedding model,
# downloaded here so a pod never fetches ~220 MB at startup.
# =============================================================================
FROM base AS prod-dependencies

ARG SEMANTIC_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ENV FASTEMBED_CACHE_PATH=/opt/fastembed

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# HF_HUB_OFFLINE is deliberately NOT set anywhere: Hugging Face uploads and
# token checks need the Hub at runtime.
RUN /app/.venv/bin/python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='${SEMANTIC_MODEL}')"

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
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    WEB_CONCURRENCY=1

COPY --from=prod-dependencies /app/.venv /app/.venv
COPY --from=prod-dependencies /opt/fastembed /opt/fastembed
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
