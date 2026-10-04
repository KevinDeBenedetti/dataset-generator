# Dataset Generator

[![CI](https://github.com/KevinDeBenedetti/dataset-generator/workflows/CI/badge.svg)](https://github.com/KevinDeBenedetti/dataset-generator/actions)
[![codecov](https://codecov.io/gh/KevinDeBenedetti/dataset-generator/graph/badge.svg)](https://codecov.io/gh/KevinDeBenedetti/dataset-generator)

Automatic dataset generation tool for question-answer datasets with advanced export capabilities and LLM integration.

## 🎯 Objective

Create quality datasets for training AI models by mining uploaded files and GitHub repositories, generating contextualized question-answer pairs. Datasets are stored in PostgreSQL and can be exported to multiple formats.

## ⚡ Quick Start

```bash
# Configuration
cp .env.example .env
# Edit .env with your API keys

# Launch (builds if needed, then streams logs; Ctrl-C stops the stack)
make dev
```

## 🏗️ Architecture

This project is designed with a modular architecture that separates concerns into distinct components:

- **LLM Client**: Interaction with language models to generate question-answer pairs
- **Data Manager**: Data management and dataset storage with multiple export formats
- **Pipeline**: Orchestration of the complete dataset generation process
- **Export Module**: Advanced dataset export to various formats (JSON, JSONL, CSV) and dataset copies

## ✨ Key Features

- **Multi-source Ingestion**: File uploads (PDF/image, via a vision model) and single web pages, from the **Generate** page
- **Dataset jobs**: recurring sources (GitHub personal Q&A, knowledge corpus) defined in code, run on a GitHub Actions schedule or on demand from the **Jobs** page
- **Model providers**: every call (cleaning, Q&A, vision, jobs) runs on the user's own OpenAI-compatible key — or, in local development and CI, on a Claude subscription (Claude Agent SDK); per-step defaults are set on the **Models** page
- **AI-Powered QA Generation**: Leverage state-of-the-art LLMs for intelligent question-answer pair creation
- **Multi-language Support**: Generate datasets in French, English, Spanish, and German
- **Versioned storage**: datasets are created/updated in PostgreSQL at generation time, with DVC-like versioning — each generation is recorded as a numbered run (`v1`, `v2`, …) and pairs are idempotent by content hash
- **Multiple Export Formats**: JSON, CSV, JSONL, and platform-specific formats
- **Quality Control**: Automated validation and filtering of generated content
- **Batch Processing**: Efficient handling of large-scale data generation
- **API Interface**: RESTful API for programmatic access and integration

## 🔄 Workflow

1. **Ingestion**: Reading raw content from an uploaded file (transcribed page-by-page via a vision model) or a web page
2. **Cleaning**: Processing and normalizing text to extract relevant content (per page)
3. **QA Generation**: Creating high-quality question-answer pairs via LLMs with configurable prompts
4. **Quality Assurance**: Automated validation, semantic deduplication (local multilingual sentence embeddings) and answer-grounding checks of generated datasets
5. **Versioning & Export**: Automatic save at generation time (versioned runs), plus multi-format export
6. **Storage**: Persistent storage with metadata tracking and version control

## 📊 Export Options

- **Hugging Face Hub**: Push a dataset to your account as a **private** dataset repo
- **Qdrant**: Optional vector store for semantic search over a dataset
- **JSON/JSONL**: Standard formats for data interchange
- **CSV**: Tabular format for analysis and review
- **Custom Formats**: Extensible export system for specific requirements

## 🔧 Configuration

Everything is configured through `.env` (copy `.env.example`). The file is
deliberately short: only what differs between deployments is a variable; tuning
values are constants in `apps/server/core/config.py`, and everything a
deployment can't get wrong follows from **`ENVIRONMENT`**.

| | `ENVIRONMENT=development` (local) | anything else (production) |
| --- | --- | --- |
| Session cookies | plain names, http | `__Host-` prefixed, Secure (https only) |
| Sign-in | SSO + email/password | SSO only (`ENABLE_LOCAL_LOGIN=true` to allow passwords) |
| Model keys | a user's own, else the server's `OPENAI_API_KEY`, `HF_TOKEN`… | the user's own only |
| Claude subscription provider | available (also in CI) | never offered |
| `/docs`, `/openapi.json` | on | off |
| Encryption key ring | derived from `AUTH_SECRET_KEY` | `SECRETS_ENCRYPTION_KEYS` required |
| Startup checks | none | refuses to boot without `DATABASE_URL`, `SECRETS_ENCRYPTION_KEYS`, a real `AUTH_SECRET_KEY`, an https `FRONTEND_URL` and a sign-in method |

### Local stack

`make dev` runs Next, the API, a job worker, Postgres, Qdrant and Redis.
`docker-compose.yml` fills in the in-network URLs (`DATABASE_URL`, `REDIS_URL`,
`QDRANT_URL`), the public URLs (`FRONTEND_URL`, `API_PUBLIC_URL`,
`NEXT_PUBLIC_API_BASE_URL`) from the ports, and `ENVIRONMENT=development` — so a
local `.env` needs little more than your own keys. Host ports follow this
project's dev lane (slot 2): web `3020`, API `8020`, Postgres `5452`, Qdrant
`6353`, Redis `6399`; override with `NEXT_PORT`, `SERVER_PORT`,
`POSTGRES_HOST_PORT`, `QDRANT_HOST_PORT`, `REDIS_HOST_PORT`.

`make dev-local` runs the API outside Docker (on `:8000`, with a worker inside
the process) against the compose Postgres through its host port.

Dev accounts (`SEED_DEV_USERS=true`, development only): `admin@example.com` /
`user@example.com`, passwords `DEV_ADMIN_PASSWORD` / `DEV_USER_PASSWORD` (weak
built-in defaults in development; outside it seeding refuses to run without them).
`DEBUG_LOGS=1` streams both servers' logs into an in-browser console (Ctrl+`) —
it exposes raw logs, so never outside your machine.

### Production

One public host: the ingress sends `/api/*` to the API (prefix stripped) and the
rest to Next. Set `FRONTEND_URL=https://<host>`; the API is then
`https://<host>/api` (override with `API_PUBLIC_URL`), the SSO callbacks to
register are `https://<host>/api/auth/infomaniak/callback` and
`https://<host>/api/auth/github/callback`, and there is no CORS to configure.
Behind a proxy set uvicorn's `FORWARDED_ALLOW_IPS` so rate limits see the client
address. Health: `GET /health` (liveness, no database) and `GET /ready` (Postgres).
With `RUN_MIGRATIONS_ON_STARTUP=false`, migrations are left to a deployment step
(they run under a Postgres advisory lock either way).

`SECRETS_ENCRYPTION_KEYS` encrypts the keys users store: generate an entry with
`python -m server.cli gen-key`, and **back it up apart from the database** —
losing it means every user re-enters their keys. Rotate by prepending a new key,
running `python -m server.cli rewrap-secrets`, then dropping the old one.

### Images and deployment

`.github/workflows/images.yml` builds the production images (`target: prod`) and
publishes them to GHCR: `ghcr.io/<owner>/dataset-generator-server` (the API **and**
the job worker — same image, the worker just runs `python -m server.worker`) and
`ghcr.io/<owner>/dataset-generator-next`. A `v*` tag (made when the release-please
PR is merged on `main`) produces `:vX.Y.Z` and `:latest`; a manual run from
`main` tags `:sha-<short>`. Nothing is built from other branches, and a tag that
is not on `main` is refused. amd64 only unless the
`IMAGE_PLATFORMS` repository variable says otherwise (`linux/amd64,linux/arm64`).
A release is only deployable once that workflow is green — a tag without an image
leaves the deployment's migration Job in `ImagePullBackOff`.

What a deployment runs, from the server image:

| Workload | Command | Probes |
| --- | --- | --- |
| API | *(image default)* uvicorn, `WEB_CONCURRENCY` workers | liveness `GET /health`, readiness `GET /ready` |
| Worker | `python -m server.worker` | — (drains on SIGTERM) |
| Migration Job | `python -m server.cli migrate` | runs once per release, before the pods roll |

Set `RUN_MIGRATIONS_ON_STARTUP=false` on the API and the worker when a Job migrates.
Containers run as uid 10001 and need no writable root filesystem. The local
embedding model is baked into the server image; `HF_HUB_OFFLINE` must stay unset
(uploads and token checks need the Hub). Leave `ENVIRONMENT` unset (= production),
and do not set `ALLOW_ENV_CREDENTIALS` or `ENABLE_CLAUDE_PROVIDER`: they no longer
exist — production never lends the server's keys and never offers Claude.

Required in the deployment's secrets/config: `DATABASE_URL`, `AUTH_SECRET_KEY`,
`SECRETS_ENCRYPTION_KEYS`, `FRONTEND_URL` (https), and at least one SSO pair
(`INFOMANIAK_CLIENT_ID`/`SECRET` or `GITHUB_CLIENT_ID`/`SECRET`); recommended:
`ADMIN_EMAILS`, `REDIS_URL`, `QDRANT_URL`, `FORWARDED_ALLOW_IPS`. The Next image
needs only `API_INTERNAL_URL` (the API's in-cluster URL).

### Sign-in and roles

Users sign in with **Infomaniak** (OpenID Connect) or **GitHub** (an OAuth App,
scopes `read:user user:email`); a provider is offered once its client id and
secret are set. Both flows use state + PKCE (S256). A sign-in is matched on the
provider's stable id (GitHub's numeric user id, never the login); it joins an
existing account only through a **verified** email, or when the signed-in user
links it from **Settings → Sign-in methods**. The last sign-in method can't be
removed; **Sign out everywhere** revokes every session at once.

Two roles, `user` and `admin`. Verified emails listed in `ADMIN_EMAILS` are made
admin at sign-in, may always sign up, and can't be demoted or disabled. Break-glass:
`python -m server.cli promote-admin you@example.com`.

Sessions: a 15-minute access JWT plus a single-use, rotated refresh token (14
days idle). Replaying a rotated refresh token revokes its whole family (except
within 10 s, for two tabs refreshing at once). Login failures, refreshes and SSO
starts are throttled per IP — through Redis when `REDIS_URL` is set, so the
limits hold across replicas.

### Backoffice (admins)

`/admin` — accounts, audit log, usage, platform switches. Admins see accounts and
*counts* (datasets, pairs, runs, which kinds of keys are saved), never dataset
content, settings values or keys. They change roles, disable (immediate sign-out)
and delete accounts (with their data and Qdrant collections; their Hugging Face
repos stay). The **Platform** tab holds the switches that used to be env vars:
open sign-up, allowed email domains, the OpenAI-compatible hosts users may use,
any public endpoint. Every user can export their data and delete their account
from **Settings → Your data**.

### Per-user data and keys

Every dataset, run, model default and quality-rule set belongs to a user;
another user's resource answers **404**. `tests/api/test_tenant_isolation.py` walks
every route and fails on any new one it can't classify.

Each user enters their own OpenAI key, Hugging Face token and GitHub details in
**Settings** (and, in development, a Claude token). Secrets are encrypted at rest
(AES-256-GCM, bound to the user and the kind), checked against their provider
when saved, and **write-only**: no route returns one. Calls to a user-chosen
endpoint go through `core/net.py` (https, public addresses only, pinned
connection, no redirects).

Upgrading a single-user install: existing data goes to the oldest admin, or to an
inactive `system` account until `python -m server.cli claim-legacy --email you@example.com`
(or the first sign-in of an `ADMIN_EMAILS` account) takes it.

### Jobs

The API **queues** dataset jobs; a worker (`python -m server.worker`, the `worker`
service) executes them, with the owner's own keys. Any number of workers can run
(`FOR UPDATE SKIP LOCKED`). A run whose worker dies becomes **interrupted** after
two minutes and is never re-run on its own. SIGTERM drains for
`WORKER_DRAIN_SECONDS`. Per-user quotas: `QUOTA_ACTIVE_RUNS`, `QUOTA_RUNS_PER_DAY`,
`QUOTA_DATASETS` (`0` = unlimited).

The scheduled GitHub Actions jobs run the same code on the server's own keys
(`OPENAI_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `HF_TOKEN`, `GITHUB_TOKEN`,
`HF_QA_DATASET_REPO`… as repository secrets and variables).

### Storage

PostgreSQL is the only database (`postgres://` / `postgresql://` URLs are
accepted). Three tables hold the datasets: `datasets`, `qa_pairs` (keyed by
`(dataset_id, content hash)`, so re-running a generation is idempotent) and
`dataset_runs` (one numbered version per generation). `PERSIST_DATASETS=false`
makes generation a pass-through (also per request: `persist`). Qdrant is optional
(`QDRANT_URL`); `QDRANT_COLLECTION_PREFIX` lets environments share one instance.
Hugging Face exports are always **private** repos — an export into an existing
public repo is refused.

## 🌍 Supported Languages

- **French (fr)**: French language dataset generation
- **English (en)**: English language dataset generation
- **Spanish (es)**: Spanish language dataset generation
- **German (de)**: German language dataset generation

## 🧪 Testing & Coverage

This project maintains high test coverage to ensure code quality and reliability.

The suite runs against a **real PostgreSQL instance**, started as a throwaway
container by [testcontainers](https://testcontainers-python.readthedocs.io/), so
a reachable Docker daemon is required. One container is shared by the whole
session and the schema is recreated around each test. To reuse an already-running
Postgres instead (and skip the container), point `TEST_DATABASE_URL` at it —
be aware the suite drops and recreates its tables there.

```bash
# Run tests with coverage (HTML report)
make test

# Run tests for CI (XML report, enforces 70% minimum)
make test-ci

# Run pre-commit hooks (includes tests on push)
uv run prek run --all-files
```

### Git hooks

Hooks are managed by [prek](https://prek.j178.dev/) and declared in a single
`prek.toml` at the repo root — there is no `.pre-commit-config.yaml`. The shims
are installed by `make setup` (`uv run prek install`).

Two things keep the hooks honest with CI: the linters run through `uv run` /
`bun run`, so they use the versions already pinned in `pyproject.toml` and
`apps/next/package.json`; and everything prek ships natively (whitespace, EOF,
YAML/JSON/TOML syntax, private keys, …) uses `repo = "builtin"` — offline, no
environment to build, no `rev` to bump.

```bash
uv run prek run --all-files      # every hook, every file
uv run prek run                  # staged files only
uv run prek run ruff             # a single hook
uv run prek run --stage pre-push # includes the test suite
uv run prek util list-builtins   # what "builtin" provides
```

`hadolint-docker` needs a running Docker daemon, and the `pytest` hook (pre-push
only) needs one too — the suite starts a throwaway Postgres.

### Coverage Reports

- **Local**: After running tests, view `htmlcov/index.html` for detailed coverage report
- **CI/CD**: Coverage reports are automatically generated and uploaded on every PR
- **Codecov**: [View detailed coverage on Codecov](https://codecov.io/gh/KevinDeBenedetti/dataset-generator)

Current coverage threshold: **70%** minimum required for CI to pass

### API schema & client

`apps/next/openapi.json` is the committed contract between the two apps. The
TypeScript client is **generated from it, never committed**: `apps/next/api/gen/`
is gitignored and rebuilt before every `bun run dev`, `build`, `typecheck` and
`test` (`pre*` scripts), like a dependency. The hand-written wrappers the app
actually imports (`api/sdk.ts`, `api/types.ts`) sit one level up.

```bash
# After changing an endpoint or schema: dump the contract (no server needed),
# regenerate the client, then commit openapi.json
make api-client

# What CI runs (`API schema drift` job): fails when openapi.json is stale
make api-check

# Optional, while working on the API: regenerate the client whenever the
# running FastAPI server's schema changes (OPENAPI_INPUT overrides the URL)
cd apps/next && bun run api:watch
```

A few details keep generation deterministic:

- The dump preserves the app's own key order rather than sorting it — the
  generator emits operations in schema order, so sorting would churn the diff.
- The generator runs from an isolated install in `apps/next/openapi-codegen`:
  it needs the TypeScript 5 compiler API, which the app's typescript@7 (native
  tsgo) no longer ships.
- `openapi-ts.config.ts` sets `baseUrl: false` on the client plugin, so no base
  URL is baked into `client.gen.ts` from whatever input was used; `api/sdk.ts`
  supplies the real one at runtime from `NEXT_PUBLIC_API_BASE_URL`.
