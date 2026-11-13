# syntax=docker/dockerfile:1

# =============================================================================
# Stage: base
# Common base configuration
# =============================================================================
# Pinned by tag and digest (dependabot bumps both).
FROM oven/bun:1.4.4-slim@sha256:1846adf22496bd711036aae8be147e57bdebbaea2e5264e3e0b5af1db187d9a4 AS base

WORKDIR /app

# =============================================================================
# Stage: dependencies
# Install dependencies with cache
# =============================================================================
FROM base AS dependencies

# Copy only dependency files to maximize cache (patches/: package.json's
# patchedDependencies, applied by `bun install`)
COPY package.json bun.lock ./
COPY patches ./patches

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

# Install only openssl (nodejs is already in the bun slim image)
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

# Install from the lockfile, then start. docker-compose.yml mounts a named
# volume over /app/node_modules, and that volume outlives image rebuilds: a
# package added since it was created would be missing ("Module not found")
# until installed by hand. With nothing to install this takes about a second.
CMD ["sh", "-c", "bun install --frozen-lockfile && exec bun run dev"]

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
FROM node:24-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS prod

ARG APP_PORT=3000
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=${APP_PORT} \
    HOSTNAME=0.0.0.0

WORKDIR /app

# Debian security updates not yet folded into the node:24-slim tag (e.g.
# perl-base CVE-2026-13221/-42496/-8376, CRITICAL in Trivy): apply them here
# rather than wait for an upstream rebuild.
# Then the package managers go: this stage only runs `node server.js` (and the
# `node -e` healthcheck), and the npm bundled with the base image carried every
# CVE Trivy reported for this image, none of them from the app's lockfile.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack /opt/yarn-v* /usr/local/bin/yarn /usr/local/bin/yarnpkg

COPY --from=builder --chown=1000:1000 /app/.next/standalone ./
COPY --from=builder --chown=1000:1000 /app/.next/static ./.next/static
# public/ is empty today (its .gitkeep keeps the directory): still copied, so an
# asset added later ships without touching this file.
COPY --from=builder --chown=1000:1000 /app/public ./public

# Numeric: Kubernetes' runAsNonRoot can only verify a numeric uid (node = 1000).
USER 1000
EXPOSE ${APP_PORT}

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:'+process.env.PORT+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

CMD ["node", "server.js"]
