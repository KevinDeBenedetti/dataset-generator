# Dataset Generator - AI Coding Instructions

Always use context7 when I need code generation, setup or
configuration steps, or library/API documentation. This means
you should automatically use the Context7 MCP tools to resolve
library id and get library docs without me having to
explicitly ask.

## 🔭 Project Overview

This is a monorepo for a dataset generation tool that scrapes web content and uses LLMs to generate QA pairs.

- **Architecture**: Dockerized microservices (Next.js Frontend + FastAPI Backend).
- **Goal**: Automate dataset creation for AI training/fine-tuning.

## 🏗 Architecture & Core Components

### Backend (`apps/server`)

- **Framework**: FastAPI with Pydantic for validation.
- **Database**: SQLAlchemy (ORM) with Alembic (migrations).
- **AI/ML**:
  - `openai` client for LLM interactions.
  - `instructor` for structured outputs.
  - `scrapy` & `requests` for web scraping.
- **Key Directories**:
  - `api/`: API route handlers (endpoints).
  - `core/`: Config (`config.py`), database connection, logging.
  - `models/`: SQLAlchemy database models.
  - `schemas/`: Pydantic models for request/response validation.
  - `pipelines/`: Logic for scraping and generation workflows.
  - `migrations/`: Database migration scripts.

### Frontend (`apps/next`)

- **Framework**: Next.js 16 (React 19).
- **Styling**: Tailwind CSS v4.
- **State**: Zustand.
- **API Client**: Generated via `@hey-api/openapi-ts`.
- **Note**: `apps/vue` exists but is currently commented out in `docker-compose.yml`. Focus on `apps/next` unless instructed otherwise.

### Infrastructure

- **Docker**: `docker-compose.yml` orchestrates services.
- **Package Managers**:
  - Python: `uv`
  - JavaScript: `bun` (preferred) or `npm`/`pnpm`.

## 🛠 Critical Workflows

### Development

- **Start Stack**: `make start` (Runs `docker-compose up`).
- **Clean**: `make clean` (Removes containers, volumes, cache, lockfiles).
- **Linting**: `make lint` (Runs `ruff` for Python, `eslint` for JS).

### Database Changes

1. Modify models in `apps/server/models/`.
2. Generate migration: `uv run alembic revision --autogenerate -m "message"`.
3. Apply migration: `uv run alembic upgrade head` (or restart container).

### API Updates

When adding/modifying backend endpoints:

1. Update `apps/server/api/`.
2. Update Pydantic schemas in `apps/server/schemas/`.
3. Regenerate frontend client:
   ```bash
   cd apps/next
   npm run api:generate
   ```

## 📏 Conventions & Patterns

### Python (Backend)

- **Type Hints**: Mandatory for all function arguments and return values.
- **Configuration**: Use `apps/server/core/config.py` and `.env`. Do not hardcode secrets.
- **Logging**: Use `server.core.logger`.
- **Async**: Prefer `async def` for route handlers and IO-bound operations.

### TypeScript (Frontend)

- **API Integration**: Do NOT use `fetch` directly. Use the generated client from `@/api/client` (or similar path).
- **Components**: Use functional components with hooks.
- **Styling**: Use Tailwind utility classes.

### General

- **Environment**: Copy `.env.example` to `.env` for local setup.
- **Docker**: Ensure `Dockerfile` in apps is updated if system dependencies change.

## 🔍 Contextual Helpers

- **Routes**: See `apps/server/main.py` for router inclusion order.
- **Scraping Logic**: Check `apps/server/pipelines/` for the core business logic connecting scraping to LLM generation.
