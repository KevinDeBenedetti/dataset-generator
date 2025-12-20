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
    CMD curl -f http://localhost:${APP_PORT}/api/health || exit 1

# Use bun dev directly without reinstalling
CMD ["bun", "run", "dev"]
