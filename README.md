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
- **Two model providers**: every call (cleaning, Q&A, vision, jobs) can run on the OpenAI-compatible API or on a Claude subscription (Claude Agent SDK, `CLAUDE_CODE_OAUTH_TOKEN`); per-step defaults are set on the **Models** page
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

The tool supports extensive configuration options for:

- LLM model selection and parameters
- Export format preferences
- Quality thresholds and validation rules
- Batch processing settings
- API rate limiting and retry policies

### Versioning

Dataset versioning is controlled by this environment variable (sensible default — add it to your `.env` to override):

| Variable | Default | Description |
| --- | --- | --- |
| `PERSIST_DATASETS` | `true` | Store the generated pairs and record a version at generation time |

This can also be overridden per request: the `POST /dataset/generate/file` and `POST /dataset/generate/url` bodies accept `persist`, and the **Generate** page exposes it as a form control.

### Database (PostgreSQL)

The application database is **PostgreSQL** — it is the only supported backend,
and `DATABASE_URL` is rejected at startup if it isn't a PostgreSQL URL. It holds
everything: the operational tables (`users`, `refresh_tokens`, `quality_rules`)
and the datasets themselves (`datasets`, `qa_pairs`, `dataset_runs` — see below).

`make dev` starts a `postgres` service and the server connects to it in-network
at `postgres:5432`. It is also published on the host at `5452` (this project's
dev-port lane) for `psql` or a GUI client. Alembic migrations run automatically
from the server's startup lifespan, so a fresh volume is schema-ready on first
boot. Data persists in the `postgres_data` volume — note that `make reset` uses
`docker compose down -v` and therefore **destroys it**.

| Variable | Default | Description |
| --- | --- | --- |
| `POSTGRES_USER` | `datasets` | Role created by the compose service; also used to build the server's `DATABASE_URL` |
| `POSTGRES_PASSWORD` | `datasets` | Password for that role (change it in any shared environment) |
| `POSTGRES_DB` | `datasets` | Database name |
| `POSTGRES_HOST_PORT` | `5452` | Host port published for external clients (the server always uses `5432` in-network) |
| `DATABASE_URL` | _(built from the vars above)_ | Set only to point at a Postgres outside compose, e.g. a managed instance. `postgres://` and `postgresql://` are accepted and rewritten to the `psycopg` (v3) driver |

Running the server outside Docker (`make dev-local`) needs no extra setup: with
`DATABASE_URL` unset it targets the compose Postgres through the published host
port, using the same `POSTGRES_*` credentials.

### How datasets are stored

Three tables hold everything the dataset pages show, all in the same Postgres:

- `datasets` — one row per named dataset. The **name** is the identifier every route and the front-end use; ids stay internal.
- `qa_pairs` — the generated pairs, with `question`/`answer`/`context`/`source_url`/`confidence` as real columns (so the Q/A list paginates, the stats aggregate and the sources view groups in SQL). The primary key is `(dataset_id, content hash)`, which makes re-running a generation idempotent while keeping the same content in two datasets as two independent rows.
- `dataset_runs` — one row per generation: the seed that was analysed, the version (`v1`, `v2`, …) and the counters behind the history view.

- **Writes**: generation stores its pairs and records a run at the end of the pipeline (see `PERSIST_DATASETS`/`persist` above). Turning that off makes generation a pass-through: the pairs come back in the API response and nothing is stored.
- **Deletion**: `DELETE /dataset/{name}` drops the dataset, its pairs and its runs (`ON DELETE CASCADE`), then its Qdrant collection.

### Hugging Face export

`POST /dataset/{name}/export/huggingface` (admin only) pushes a dataset to the
Hub as a **private** dataset repo, and the Datasets detail page has a button for
it. Two files are written: `data/train.jsonl` (one Q/A pair per line) and a
`README.md` dataset card whose front matter points the Hub viewer at that file.

| Variable | Default | Description |
| --- | --- | --- |
| `HF_TOKEN` | _(none — required for the export)_ | Hugging Face token with **write** access ([settings/tokens](https://huggingface.co/settings/tokens)). Without it the endpoint answers `503` |
| `HF_NAMESPACE` | _(the token's own account)_ | User or organization the repo is created under |

The repo id defaults to `<namespace>/<dataset-name-slug>`; pass `repo_id` to
override it. There is deliberately **no public option**: generated datasets carry
source text pulled from the input file/repo, so the repo is always created with
`private=True`. Because
the Hub ignores `private` when the repo already exists, an export into a repo
that is already public is refused with a `409` rather than publishing the data —
make that repo private on the Hub, or export to a different id.

### File uploads (PDF/image)

`POST /dataset/generate/file` reads each page with a vision-capable model, so `OPENAI_VLM_MODEL` is **required** for this source — without it the endpoint returns `400 No vision model configured`. It can also be overridden per request via the `model_vlm` form field.

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_VLM_MODEL` | _(none — required for file uploads)_ | Vision model used to transcribe each page of an uploaded PDF/image into text before QA generation |

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
| `AUTH_SECRET_KEY` | _(insecure dev default)_ | HS256 signing key for the session JWT — **required** outside `ENVIRONMENT=development`: the server refuses to start with the dev default |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | Uvicorn setting: proxies whose `X-Forwarded-For` is trusted. Set it to the reverse proxy's address, or the login rate limit sees the proxy's IP for every client |
| `AUTH_TOKEN_TTL_SECONDS` | `900` | Access-token (JWT) lifetime — kept short; the session is renewed by the refresh token below |
| `AUTH_REFRESH_TOKEN_TTL_SECONDS` | `1209600` | Refresh-token lifetime (max idle time before a fresh login is required) |
| `AUTH_COOKIE_NAME` | `access_token` | Name of the httpOnly access-token cookie |
| `AUTH_REFRESH_COOKIE_NAME` | `refresh_token` | Name of the httpOnly refresh-token cookie |
| `AUTH_COOKIE_SECURE` | `false` | Send the cookies only over HTTPS (enable behind TLS) |
| `CORS_ALLOW_ORIGINS` | _(falls back to `FRONTEND_URL`)_ | Comma-separated browser origins allowed to call the API with credentials — see below |

Because the session lives in cookies, CORS is **credentialed** and the allowed
origins are always explicit: `allow_origins=["*"]` is not usable here, since
Starlette answers a credentialed request by reflecting the caller's origin,
which would let any site read authenticated responses. Set
`CORS_ALLOW_ORIGINS` (or leave it unset to allow `FRONTEND_URL` alone) to the
origin(s) serving the UI. While `ENVIRONMENT=development`, any `localhost` /
`127.0.0.1` origin is additionally accepted, so moving the front to another dev
port doesn't require touching this.

#### Access & refresh tokens

Login issues two httpOnly cookies: a short-lived access JWT and a long-lived
**refresh token**. The refresh token is opaque, stored **hashed** in the
`refresh_tokens` table, and **single-use** — `POST /auth/refresh` revokes the
presented token and issues a successor in the same *family*. When the access
token expires, the frontend transparently calls `/auth/refresh` on the first
`401` and replays the request, so users aren't logged out at the TTL boundary.

Rotation is **atomic** (a conditional `UPDATE`, so two concurrent requests
can't both consume one token). Replaying an already-rotated refresh token is
treated as theft: the **entire family is revoked**, forcing a fresh login on
every device that held a token from it — except within
`AUTH_REFRESH_REUSE_GRACE_SECONDS` (default 10) of the rotation, where a second
tab or the Next server racing the first is answered with its own successor
instead (never for a token revoked by logout or by a replay; `0` disables the
grace). `POST /auth/logout` revokes the family server-side and clears both
cookies.

The cookie names are `AUTH_COOKIE_NAME` / `AUTH_REFRESH_COOKIE_NAME`. The Next.js
proxy (`apps/next/proxy.ts`) reads the **same two variables at runtime** to
recognise a renewable session (no rebuild needed). Their default is
`access_token` / `refresh_token` in development and `__Host-access_token` /
`__Host-refresh_token` everywhere else.

### Production hardening

Outside `ENVIRONMENT=development` the server **refuses to start** unless the
configuration is safe, and lists every problem at once (`Config.production_problems`):
`AUTH_COOKIE_SECURE=true`, `__Host-` cookie names, an explicit `DATABASE_URL`
(there is no fallback to the local dev database), `SESSION_SECRET_KEY` set and
different from `AUTH_SECRET_KEY`, and an https `FRONTEND_URL`. Also, outside
development: `/docs` and `/openapi.json` are off (`DOCS_ENABLED`), email/password
login is off (`ENABLE_LOCAL_LOGIN`; accounts sign in through SSO), and every
response carries security headers (HSTS, `nosniff`, `frame-ancestors 'none'`,
`no-store` on `/auth`). State-changing requests from a foreign browser `Origin`
are refused (CSRF), and `/auth/refresh` and the SSO start are throttled per IP
(`AUTH_REFRESH_MAX_PER_MINUTE`, `AUTH_SSO_MAX_PER_MINUTE`). The OAuth state cookie
is signed with its own `SESSION_SECRET_KEY` and lives ten minutes.

Health probes: `GET /health` is liveness (never touches the database) and
`GET /ready` is readiness (`SELECT 1`; 503 while Postgres is down). Migrations
run under a Postgres advisory lock, and `RUN_MIGRATIONS_ON_STARTUP=false` leaves
them to a deployment step (a Kubernetes pre-upgrade Job).

Topology: **one public host** — the ingress sends `/api/*` to the API (stripping
the prefix) and everything else to Next. There is no CORS to configure, the
cookies are host-only, `NEXT_PUBLIC_API_BASE_URL` stays unset (it defaults to the
same-origin `/api` in production), and the SSO callbacks to register are
`https://<host>/api/auth/<provider>/callback`. Behind an ingress set
`FORWARDED_ALLOW_IPS` so the rate limiters see the real client address. The Next
server sets a per-request `Content-Security-Policy` with a nonce in production.

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

Auth endpoints: `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`,
`GET /auth/me`, and the OIDC flow `GET /auth/oidc/login` →
`GET /auth/oidc/callback`.

> 📖 For the full picture — roles and which routes are admin-only, refresh-token
> rotation and theft detection, login throttling and its Redis backend, the OIDC
> account-resolution rules, every auth env var and a troubleshooting section —
> see [docs/authentication.md](docs/authentication.md).

### Sign-in (Infomaniak, GitHub) and roles

Users sign in with **Infomaniak** (OpenID Connect) or **GitHub** (OAuth App);
email + password is a development convenience (`ENABLE_LOCAL_LOGIN`). Both flows
use state + PKCE (S256); Infomaniak's ID token and nonce are checked by Authlib.
The login page only shows the providers that are configured (`GET /auth/providers`).

| Variable | Default | Description |
| --- | --- | --- |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | _(empty)_ | Infomaniak. Callback: `https://<host>/api/auth/infomaniak/callback` (the older `/auth/oidc/callback` still works). |
| `OIDC_REDIRECT_URI` | `http://localhost:8000/auth/oidc/callback` | The callback URL registered with Infomaniak. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | _(empty)_ | A GitHub **OAuth App** (github.com/settings/developers). Scopes `read:user user:email`. |
| `GITHUB_REDIRECT_URI` | `http://localhost:8000/auth/github/callback` | Its callback URL, e.g. `https://<host>/api/auth/github/callback`. |
| `ADMIN_EMAILS` | _(empty)_ | Comma-separated. These (verified) emails are made admin at sign-in, may sign up even when sign-up is closed, and receive the data parked on the `system` user. |
| `ALLOW_SIGNUP` | `true` | Whether a first SSO sign-in creates an account. |
| `ALLOWED_EMAIL_DOMAINS` | _(empty)_ | Restrict sign-ups to these email domains. |
| `SSO_TRUSTED_EMAIL_PROVIDERS` | `infomaniak,github` | Providers whose *verified* email may attach a sign-in to an existing account with that email. |

Account linking (`services/identities.py`): a sign-in is matched on the
provider's stable id (`provider` + `subject` — GitHub's numeric user id, never
the login). A new identity joins an existing account only when the provider
says the email is **verified** and is trusted, or when the signed-in user links
it from **Settings → Sign-in methods**. An unverified email never links and
never creates an account. The last sign-in method can't be removed.
**Sign out everywhere** revokes every refresh token and refuses every access
token issued before it; a deactivated account is refused on its next request.
Security events (sign-up, link, promotion…) are written to `audit_log`.

Break-glass, from inside the deployment: `python -m server.cli promote-admin you@example.com`.

### Job workers and quotas

The API never runs a dataset job: it **queues** it (a `job_runs` row,
`queued`), and a worker executes it — `python -m server.worker` (the `worker`
service in `docker-compose.yml`; `make dev-local` runs one inside the API with
`EMBEDDED_WORKER=true`). Workers claim with `FOR UPDATE SKIP LOCKED`, so any
number can run side by side. The worker reads the run owner's own keys when it
starts the run; nothing secret is stored in the queue.

A running job heart-beats; if its worker dies (crash, `kill -9`, node lost) the
run becomes **interrupted** after `WORKER_STALE_SECONDS` — never re-run on its
own, since it may already have spent model quota or published. SIGTERM drains:
the worker stops claiming and lets its current runs finish for
`WORKER_DRAIN_SECONDS`. Queued and running runs can be cancelled from the Jobs
page. Publishing a draft is atomic: a double click publishes once.

| Variable | Default | Description |
| --- | --- | --- |
| `WORKER_CONCURRENCY` | `1` | Runs one worker process executes at once. |
| `WORKER_POLL_SECONDS` / `WORKER_HEARTBEAT_SECONDS` | `2` / `10` | Queue polling and heartbeat periods. |
| `WORKER_STALE_SECONDS` | `120` | Heartbeat age after which a running job is marked interrupted. |
| `WORKER_DRAIN_SECONDS` | `25` | Grace on SIGTERM (keep below the pod's `terminationGracePeriodSeconds`). |
| `EMBEDDED_WORKER` | `false` | Also run a worker inside the API process (single-process local runs). |
| `QUOTA_ACTIVE_RUNS` | `2` | Queued + running runs per user (`0` = unlimited). |
| `QUOTA_RUNS_PER_DAY` | `20` | Runs a user may start in 24 h. |
| `QUOTA_DATASETS` | `50` | Datasets per user. |

### Backoffice (admins)

`/admin` (sidebar **Backoffice**, admins only — every `/admin` API route requires
the admin role, and `tests/api/test_admin.py` walks them all):

- **Users** — email, sign-in methods, role, status, dates, *counts* of datasets,
  pairs and runs, and which kinds of keys are saved. Never dataset names or
  content, settings values or keys; no impersonation. Change a role, disable
  (signs the user out at once), delete (cascade + Qdrant collections; their
  Hugging Face repos stay). The last active admin and `ADMIN_EMAILS` accounts
  can't be demoted, disabled or deleted.
- **Audit log** — sign-ups, links, role changes, deletions, platform changes.
- **Platform** — `allow_signup`, `allowed_email_domains`, `allowed_llm_hosts`,
  `allow_custom_base_url`. A value set here overrides its env var; *Reset* goes
  back to the env default. Replicas pick changes up within ~15 s.
- **Overview** — accounts, activity, datasets, pairs, runs of the last 30 days.

Every user can download their data (**Settings → Your data**, a zip of datasets
and settings without keys) and delete their account.

### Per-user data (tenancy)

Every dataset, job run, model default and quality-rule set belongs to a user;
another user's resource answers **404** (never 403, which would confirm it exists).
A dataset name is unique *per user*, and each user may have one active run per job.
New datasets use the Qdrant collection `<prefix>ds_<dataset id>`; datasets that
predate this keep the collection they already had.

Upgrading a single-user install: the migration gives all existing data to the
oldest active admin, or, if there is none yet, to an inactive `system` account.
Hand that data to a real account once it exists (run it inside the server
container or pod):

```bash
python -m server.cli claim-legacy --email you@example.com
```

The tenancy guarantees are enforced by `tests/api/test_tenant_isolation.py`, which
walks every route of the app and fails when a new one is not classified.

### Your own keys (per-user credentials)

Each user enters their own OpenAI key, Claude token, Hugging Face token and GitHub
details under **Settings**. Secrets are encrypted at rest (AES-256-GCM, bound to
the user and the kind of secret), only ever sent to their own provider, and
**write-only**: no route returns one, administrators included. Non-secret
settings (namespace, dataset repos, GitHub username, an OpenAI-compatible base
URL) are stored in clear.

| Variable | Default | Description |
| --- | --- | --- |
| `SECRETS_ENCRYPTION_KEYS` | _(required in production)_ | Key ring `id:key,id:key` (first encrypts, all decrypt). Generate an entry with `python -m server.cli gen-key`. **Back it up apart from the database** — losing it means every user re-enters their keys. Rotate: prepend a new key, run `python -m server.cli rewrap-secrets`, drop the old one. Development derives a key from `AUTH_SECRET_KEY`. |
| `ALLOW_ENV_CREDENTIALS` | `true` in development, `false` otherwise | Fill what a user hasn't entered from the server's own `OPENAI_API_KEY`, `HF_TOKEN`… A local convenience; production refuses to start with it on. |
| `ENABLE_CLAUDE_PROVIDER` | `true` in development and CI | The Claude-subscription provider runs **only in local development and in CI** (`GITHUB_ACTIONS`/`CI`). A deployed server never offers it: the Models page, the Settings keys and the defaults drop it (a saved `claude:` default falls back to the qa model), and production refuses to start with the variable set. |
| `ALLOWED_LLM_HOSTS` | _(empty)_ | Extra hosts (besides `api.openai.com`) a user's OpenAI-compatible base URL may point to. Default only — editable in the backoffice. |
| `ALLOW_CUSTOM_BASE_URL` | `false` | Let users point at any public https endpoint. Default only — editable in the backoffice. |

Every outbound request to a user-chosen address goes through `core/net.py`: https
only, public addresses only (no loopback, private, link-local or cluster names),
connection pinned to the validated address, no redirects followed. The Claude CLI
runs with a scrubbed environment in a throwaway directory, so the server's own
secrets are never visible to it. The scheduled GitHub Actions jobs keep using the
env vars (`Credentials.from_env()`).

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
