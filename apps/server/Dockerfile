# syntax=docker/dockerfile:1

# =============================================================================
# Stage: base
# Configuration de base avec UV
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
# Installation des dépendances avec cache
# =============================================================================
FROM base AS dependencies

# Copier uniquement les fichiers de dépendances pour maximiser le cache
COPY pyproject.toml uv.lock ./

# Utiliser le cache mount pour accélérer l'installation
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# =============================================================================
# Stage: dev
# Environnement de développement
# =============================================================================
FROM base AS dev

ARG APP_PORT=8000
ENV PYTHON_ENV=development

# Installer curl pour healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copier les dépendances depuis le stage précédent
COPY --from=dependencies /app/.venv /app/.venv
COPY pyproject.toml uv.lock ./

# Copier le code source
COPY ./apps/server .

EXPOSE ${APP_PORT}

# Import depuis server.main
CMD ["uv", "run", "--no-sync", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
