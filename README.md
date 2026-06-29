# Dataset Generator

[![CI](https://github.com/KevinDeBenedetti/dataset-generator/workflows/CI/badge.svg)](https://github.com/KevinDeBenedetti/dataset-generator/actions)
[![codecov](https://codecov.io/gh/KevinDeBenedetti/dataset-generator/graph/badge.svg)](https://codecov.io/gh/KevinDeBenedetti/dataset-generator)

Web scraping and automatic dataset generation tool for question-answer datasets with advanced export capabilities and LLM integration.

## 🎯 Objective

Create quality datasets for training AI models by automatically scraping reliable sources and generating contextualized question-answer pairs. Export datasets to multiple formats including Langfuse for training data management.

## ⚡ Quick Start

```bash
# Configuration
cp .env.example .env
# Edit .env with your API keys

# Launch
make start
```

## 🏗️ Architecture

This project is designed with a modular architecture that separates concerns into distinct components:

- **Scraper**: Retrieval of web content from specified URLs
- **LLM Client**: Interaction with language models to generate question-answer pairs
- **Data Manager**: Data management and dataset storage with multiple export formats
- **Pipeline**: Orchestration of the complete dataset generation process
- **Export Module**: Advanced dataset export to various platforms (Langfuse, JSON, CSV, etc.)

## ✨ Key Features

- **Multi-source Scraping**: Support for various web sources and content types
- **Whole-site Crawling**: Breadth-first crawl of the seed URL's same-domain internal links (configurable depth/page limits) to maximise the dataset from a single starting point
- **AI-Powered QA Generation**: Leverage state-of-the-art LLMs for intelligent question-answer pair creation
- **Multi-language Support**: Generate datasets in French, English, Spanish, and German
- **Langfuse Integration**: Datasets are created/updated in Langfuse at generation time, with DVC-like versioning — each run is recorded as an immutable, numbered dataset run (`v1`, `v2`, …) and items are idempotent by content hash
- **Multiple Export Formats**: JSON, CSV, JSONL, and platform-specific formats
- **Quality Control**: Automated validation and filtering of generated content
- **Batch Processing**: Efficient handling of large-scale data generation
- **API Interface**: RESTful API for programmatic access and integration

## 🔄 Workflow

1. **Scraping / Crawling**: Retrieving raw web data — a single page, or a breadth-first crawl of the whole site (same-domain internal links, bounded by depth/page limits)
2. **Cleaning**: Processing and normalizing text to extract relevant content (per page)
3. **QA Generation**: Creating high-quality question-answer pairs via LLMs with configurable prompts
4. **Quality Assurance**: Automated validation and cross-page deduplication of generated datasets
5. **Versioning & Export**: Automatic Langfuse sync at generation time (versioned dataset runs), plus multi-format export
6. **Storage**: Persistent storage with metadata tracking and version control

## 📊 Export Options

- **Langfuse**: Direct integration for training data management
- **JSON/JSONL**: Standard formats for data interchange
- **CSV**: Tabular format for analysis and review
- **Custom Formats**: Extensible export system for specific requirements

## 🔧 Configuration

The tool supports extensive configuration options for:

- LLM model selection and parameters
- Export format preferences
- Quality thresholds and validation rules
- Batch processing settings
- API rate limiting and retry policies

### Crawling & Versioning

The deep crawl and Langfuse versioning are controlled by these environment variables (with sensible defaults — add them to your `.env` to override):

| Variable | Default | Description |
| --- | --- | --- |
| `CRAWL_MAX_DEPTH` | `2` | Max link-following depth from the seed URL when crawling |
| `CRAWL_MAX_PAGES` | `50` | Max number of pages fetched per crawl (cost ceiling) |
| `CRAWL_SAME_DOMAIN` | `true` | Only follow links on the seed URL's host |
| `LANGFUSE_AUTO_SYNC` | `true` | Create/version the dataset in Langfuse at generation time (requires `LANGFUSE_*` keys) |

These can also be overridden per request: the `POST /dataset/generate` body accepts `crawl`, `max_depth`, `max_pages` and `sync_langfuse`, and the **Generate** page exposes them as form controls. Langfuse sync additionally requires `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_HOST` (the spelling `LANGFUSE_BASE_URL` is also accepted as an alias for the host).

> 📖 For a full walkthrough of how crawling works (BFS traversal, env vars, the crawl4ai service, per-request overrides and tuning), see [docs/crawling.md](docs/crawling.md).

### Authentication & dev users

The API supports two roles — `user` and `admin` — backed by a `users` table
(created by an Alembic migration that runs automatically on startup).

Two local development accounts are available:

| Email | Password (dev only) | Role |
| --- | --- | --- |
| `admin@example.com` | `DEV_ADMIN_PASSWORD` (falls back to `admin1234` in dev) | `admin` |
| `user@example.com` | `DEV_USER_PASSWORD` (falls back to `user1234` in dev) | `user` |

Seed them in either of these ways:

```bash
# A) automatically on server startup — set in your .env
ENVIRONMENT=development
SEED_DEV_USERS=true

# B) on demand, from the repo root
uv run python -m server.scripts.seed_dev_users
```

The seeding is idempotent (existing accounts are skipped). Each password comes
from its env var (`DEV_ADMIN_PASSWORD` / `DEV_USER_PASSWORD`).

> ⚠️ The weak built-in defaults (`admin1234` / `user1234`) are only used when
> `ENVIRONMENT=development`. Outside an explicitly declared development
> environment, seeding **requires** `DEV_ADMIN_PASSWORD` / `DEV_USER_PASSWORD`
> to be set and otherwise refuses to run (it will never create known-credential
> accounts). `ENVIRONMENT` defaults to `production`, so a leaked
> `SEED_DEV_USERS=true` cannot seed weak accounts on its own.

Auth is configured via these env vars:

| Variable | Default | Description |
| --- | --- | --- |
| `AUTH_SECRET_KEY` | _(insecure dev default)_ | HS256 signing key for the session JWT — **set a strong random value** outside local dev |
| `AUTH_TOKEN_TTL_SECONDS` | `86400` | Access-token lifetime |
| `AUTH_COOKIE_NAME` | `access_token` | Name of the httpOnly auth cookie |
| `AUTH_COOKIE_SECURE` | `false` | Send the cookie only over HTTPS (enable behind TLS) |

Login via **Infomaniak OIDC** is enabled only when the following are all set
(routes return `503` otherwise). Register a client with Infomaniak and add:

| Variable | Description |
| --- | --- |
| `OIDC_ISSUER` | Issuer URL (must expose `<issuer>/.well-known/openid-configuration`) |
| `OIDC_CLIENT_ID` | OIDC client id |
| `OIDC_CLIENT_SECRET` | OIDC client secret |
| `OIDC_REDIRECT_URI` | Callback URL, default `http://localhost:8000/auth/oidc/callback` |
| `OIDC_SCOPES` | Requested scopes, default `openid email profile` |
| `FRONTEND_URL` | Where to redirect after a successful login, default `http://localhost:3000` |

Auth endpoints: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, and the
OIDC flow `GET /auth/oidc/login` → `GET /auth/oidc/callback`.

### Dev log console

For local debugging you can stream both servers' logs into an in-browser terminal:

```bash
DEBUG_LOGS=1 make dev
```

| Variable | Default | Description |
| --- | --- | --- |
| `DEBUG_LOGS` | _(off)_ | When set (e.g. `1`), exposes the dev log console: FastAPI logs over SSE (`/debug/logs`), Next.js server logs captured in-process, both merged through the Next.js SSE proxy (`/api/debug/logs`) |

Once the stack is up, toggle the console with **Ctrl+`** (or the floating terminal button, bottom-right). Lines are tagged `[api]` / `[web]` by origin and colourised by level. The endpoints return `404` and the widget never renders unless `DEBUG_LOGS` is set, so it stays out of production builds.

> ⚠️ **Security — the console streams raw server logs.** Anything the code logs (request bodies, tokens, API keys, connection strings, etc.) is exposed verbatim to anyone who can reach the dev server while `DEBUG_LOGS` is on. It is a **local-dev-only** tool: keep `DEBUG_LOGS` unset in any shared, staging or production environment, and never log secret values (mask or omit them) — don't rely on the console being "dev-only" to protect sensitive data.

## 🌍 Supported Languages

- **French (fr)**: French language dataset generation
- **English (en)**: English language dataset generation
- **Spanish (es)**: Spanish language dataset generation
- **German (de)**: German language dataset generation

## 🧪 Testing & Coverage

This project maintains high test coverage to ensure code quality and reliability.

```bash
# Run tests with coverage (HTML report)
make test

# Run tests for CI (XML report, enforces 70% minimum)
make test-ci

# Run pre-commit hooks (includes tests on push)
uv run prek run --all-files
```

### Coverage Reports

- **Local**: After running tests, view `htmlcov/index.html` for detailed coverage report
- **CI/CD**: Coverage reports are automatically generated and uploaded on every PR
- **Codecov**: [View detailed coverage on Codecov](https://codecov.io/gh/KevinDeBenedetti/dataset-generator)

Current coverage threshold: **70%** minimum required for CI to pass
