# syntax=docker/dockerfile:1

# =============================================================================
# Stage: base
# Configuration de base commune
# =============================================================================
FROM oven/bun:1-slim AS base

WORKDIR /app

# =============================================================================
# Stage: dependencies
# Installation des dépendances avec cache
# =============================================================================
FROM base AS dependencies

# Copier uniquement les fichiers de dépendances pour maximiser le cache
COPY package.json bun.lock ./

# Utiliser le cache mount pour accélérer l'installation
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile

# =============================================================================
# Stage: dev
# Environnement de développement
# =============================================================================
FROM base AS dev

ARG APP_PORT=3000
ENV NODE_ENV=development

# Installer uniquement openssl (nodejs déjà dans bun:1-slim)
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends openssl curl \
    && rm -rf /var/lib/apt/lists/*

# Copier les dépendances depuis le stage précédent
COPY --from=dependencies /app/node_modules ./node_modules
COPY package.json bun.lock ./

# Copier le code source
COPY . .

EXPOSE ${APP_PORT}

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${APP_PORT}/api/health || exit 1

# Utiliser directement bun dev sans réinstaller
CMD ["bun", "run", "dev"]
