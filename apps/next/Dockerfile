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

# Install openssl, curl, and create non-root user
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends openssl curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

# Copy dependencies from the previous stage
COPY --from=dependencies /app/node_modules ./node_modules
COPY package.json bun.lock ./

# Copy source code
COPY . .

# Change ownership and switch to non-root user
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE ${APP_PORT}

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${APP_PORT}/api/health || exit 1

# Use bun dev directly without reinstalling
CMD ["bun", "run", "dev"]
