# syntax=docker/dockerfile:1

# =============================================================================
# Stage: base
# Common base configuration
# =============================================================================
FROM oven/bun:1-slim AS base

WORKDIR /app

# =============================================================================
# Stage: dependencies
# Install dependencies with cache
# =============================================================================
FROM base AS dependencies

# Copy only dependency files to maximize cache
COPY package.json bun.lock ./

# Use cache mount to speed up installation
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile

# =============================================================================
# Stage: dev
# Development environment
# =============================================================================
FROM base AS dev

ARG APP_PORT=3000
ENV NODE_ENV=development

# Install only openssl (nodejs is already in bun:1-slim)
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends openssl curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies from the previous stage
COPY --from=dependencies /app/node_modules ./node_modules
COPY package.json bun.lock ./

# Copy source code
COPY . .

EXPOSE ${APP_PORT}

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD ["sh", "-c", "curl -f http://localhost:${PORT:-3000}/api/health || exit 1"]

# Use bun dev directly without reinstalling
CMD ["bun", "run", "dev"]

# =============================================================================
# Stage: builder
# `next build` with the standalone output (server.js + only the files it needs).
# NEXT_PUBLIC_API_BASE_URL is left unset on purpose: in production the browser
# calls the API on the same origin under /api (the ingress routes it), so one
# image serves every environment — API_INTERNAL_URL is read at runtime.
# =============================================================================
FROM base AS builder

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
# `prebuild` regenerates the API client from the committed openapi.json.
RUN bun run build

# =============================================================================
# Stage: prod
# Plain Node (no bun, no sources, no devDependencies), non-root.
# =============================================================================
FROM node:22-slim AS prod

ARG APP_PORT=3000
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=${APP_PORT} \
    HOSTNAME=0.0.0.0

WORKDIR /app

# Debian security updates not yet folded into the node:22-slim tag (e.g.
# perl-base CVE-2026-13221/-42496/-8376, CRITICAL in Trivy): apply them here
# rather than wait for an upstream rebuild.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder --chown=1000:1000 /app/.next/standalone ./
COPY --from=builder --chown=1000:1000 /app/.next/static ./.next/static
COPY --from=builder --chown=1000:1000 /app/public ./public

# Numeric: Kubernetes' runAsNonRoot can only verify a numeric uid (node = 1000).
USER 1000
EXPOSE ${APP_PORT}

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:'+process.env.PORT+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

CMD ["node", "server.js"]
