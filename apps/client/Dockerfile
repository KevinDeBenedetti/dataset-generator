# Global arguments - must be provided at build time
ARG PNPM_VERSION
ARG NODE_VERSION
ARG APP_PORT

# =============================================================================
# Stage: base
# Common configuration for all stages
# =============================================================================
FROM docker.io/node:${NODE_VERSION} AS base

ARG PNPM_VERSION
ARG APP_PORT

WORKDIR /app

# Install pnpm
RUN npm install --ignore-scripts --location=global pnpm@${PNPM_VERSION}

# Copy dependency files
COPY package.json pnpm-lock.yaml* ./

# =============================================================================
# Stage: dependencies
# Dependencies installation (with cache)
# =============================================================================
FROM base AS dependencies

# Install all dependencies
RUN pnpm install --frozen-lockfile --ignore-scripts

# =============================================================================
# Stage: dev
# Development environment
# =============================================================================
FROM base AS dev

ARG APP_PORT

# Copy dependencies from previous stage
COPY --from=dependencies /app/node_modules ./node_modules

# Copy source code
COPY . .

# Expose port
EXPOSE ${APP_PORT}

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD node -e "require('http').get('http://localhost:${APP_PORT}', (r) => {process.exit(r.statusCode === 200 ? 0 : 1)})"

# Default command
CMD ["pnpm", "run", "dev", "--host", "0.0.0.0"]

# =============================================================================
# Stage: build
# Build application for production
# =============================================================================
FROM dependencies AS build

# Copy source code
COPY . .

# Environment variables for build (can be overridden)
ARG NODE_ENV=production
ENV NODE_ENV=${NODE_ENV}

# Build application
RUN pnpm run build

# =============================================================================
# Stage: prod
# Production image with Nginx
# =============================================================================
FROM docker.io/nginx:alpine AS prod

ARG APP_PORT=80

# Copy nginx configuration (adapt to your needs)
COPY --from=build /app/dist /usr/share/nginx/html

# Custom nginx configuration (optional)
# COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE ${APP_PORT}

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:${APP_PORT}/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]