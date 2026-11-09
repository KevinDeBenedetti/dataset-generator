---
title: Configuration
---

# Configuration

Everything is configured through `.env` (copy `.env.example`). The file is
deliberately short: only what differs between deployments is a variable; tuning
values are constants in `apps/server/core/config.py`, and everything a
deployment can't get wrong follows from **`ENVIRONMENT`**.

| Setting                      | `ENVIRONMENT=development` (local)                             | anything else (production)                                                                                                                |
| ---------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Session cookies              | plain names, http                                             | `__Host-` prefixed, Secure (https only)                                                                                                   |
| Sign-in                      | SSO + email/password                                          | SSO only (`ENABLE_LOCAL_LOGIN=true` to allow passwords)                                                                                   |
| Sign-up                      | open                                                          | closed until an admin opens it (backoffice **Platform** tab)                                                                              |
| Model keys                   | a user's own, else the server's `OPENAI_API_KEY`, `HF_TOKEN`… | the user's own only; with `SERVER_LLM_FOR_ADMINS=true`, an admin without one uses the server's endpoint and key                           |
| Claude subscription provider | available (also in CI)                                        | never offered                                                                                                                             |
| `/docs`, `/openapi.json`     | on                                                            | off                                                                                                                                       |
| Encryption key ring          | derived from `AUTH_SECRET_KEY`                                | `SECRETS_ENCRYPTION_KEYS` required                                                                                                        |
| Startup checks               | none                                                          | refuses to boot without `DATABASE_URL`, `SECRETS_ENCRYPTION_KEYS`, a real `AUTH_SECRET_KEY`, an https `FRONTEND_URL` and a sign-in method |

What a production deployment sets, and how it is served, is in
[Production](./production.md); who can sign in, and with which keys, in
[Accounts, roles and keys](./accounts.md).

## Models

Every model step runs on an OpenAI-compatible endpoint (OpenAI itself, or a
gateway such as LiteLLM, vLLM or Ollama) with each user's own key and base URL,
saved in **Settings**. The deployment names the defaults; on the **Models**
page each user can pick other chat models, among those configured and those
their endpoint lists.

| Variable                  | What it sets                                                                                                            |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `OPENAI_LLM_MODEL`        | The default LLM: cleaning, Q&A generation and the dataset jobs (`QA_JOB_MODEL` still overrides it for the jobs)         |
| `OPENAI_VLM_MODEL`        | The default vision model, which transcribes uploaded PDF and image pages                                                |
| `OPENAI_EMBEDDING_MODEL`  | The default embedding: the duplicate, grounding and coverage checks, and the first choice of a new collection           |
| `OPENAI_REASONING_EFFORT` | Sent to the Q&A model (default `low`); `off` for models that refuse the parameter                                       |
| `SERVER_LLM_FOR_ADMINS`   | Outside development: admins who saved no key call `OPENAI_BASE_URL` with `OPENAI_API_KEY` (other users bring their own) |

A key and its endpoint always travel together: the server's key is only ever
sent to `OPENAI_BASE_URL`, and a user's key only to the base URL they saved
(OpenAI's when blank). The server's URL may be a private `http` address, such
as an in-cluster gateway: the operator set it. A URL a user types must be a
public `https` endpoint that the backoffice allows.

The embedding checks fall back to the local `SEMANTIC_MODEL` (FastEmbed, baked
into the server image) for a user without an endpoint, or whose endpoint can't
embed with `OPENAI_EMBEDDING_MODEL`, and to comparing the words when a call
fails mid-run; `SEMANTIC_ENABLED=false` turns them off. Their thresholds
(`SEMANTIC_DEDUP_THRESHOLD`, `ANSWER_GROUNDING_THRESHOLD`,
`UNCOVERED_SECTION_THRESHOLD`) were measured on the local model: an endpoint
model scores differently, so retune them for it.

A LiteLLM gateway, for example, with a virtual key and the aliases it serves:

```sh
OPENAI_BASE_URL=http://litellm:4000/v1
OPENAI_API_KEY=sk-...
OPENAI_LLM_MODEL=chat-default
OPENAI_VLM_MODEL=chat-default
OPENAI_EMBEDDING_MODEL=embed-default
```

## Local stack

`make dev` runs Next, the API, a job worker, Postgres, Redis and Qdrant.
`docker-compose.yml` fills in the in-network URLs (`DATABASE_URL`,
`REDIS_URL`, `QDRANT_URL`), the public URLs (`FRONTEND_URL`, `API_PUBLIC_URL`,
`NEXT_PUBLIC_API_BASE_URL`) from the ports, and `ENVIRONMENT=development` — so a
local `.env` needs little more than your own keys. Host ports follow this
project's dev lane (slot 2): web `3020`, API `8020`, Postgres `5452`, Redis
`6399`, Qdrant `6353` (its dashboard: `http://localhost:6353/dashboard`);
override with `NEXT_PORT`, `SERVER_PORT`, `POSTGRES_HOST_PORT`,
`REDIS_HOST_PORT`, `QDRANT_HOST_PORT`. They are published on `127.0.0.1` only,
and the web container gets none of the server's keys.

`REDIS_PASSWORD` in `.env` puts the local Redis behind a password, and
`docker-compose.yml` adds it to the server's and the worker's `REDIS_URL`. Use
hex (`openssl rand -hex 32`): it goes into that URL as is. `make dev-local`
reads `REDIS_URL` from `.env`, so set it there as
`redis://:<password>@localhost:6399/0`.

[Vector collections](./collections.md) need `QDRANT_URL` on the API and the
worker (`QDRANT_API_KEY` too when the Qdrant requires one: set in `.env`, the
local stack's Qdrant requires it, and its dashboard asks for it); without it the
Collections page says so and builds nothing. `QDRANT_COLLECTION_PREFIX`
(default `dataset_`) lets several deployments share one Qdrant.

`make dev-local` runs the API outside Docker (on `127.0.0.1:8020`, the
`SERVER_PORT` the front-end and the SSO callbacks expect, with a worker
inside the process — the CPU-heavy steps run on their own threads, so its
heartbeats never wait behind them) against the compose Postgres through its
host port.

Dev accounts (`SEED_DEV_USERS=true`, development only): `admin@example.com` /
`user@example.com`, passwords `DEV_ADMIN_PASSWORD` / `DEV_USER_PASSWORD` (72 bytes
at most; weak built-in defaults in development; outside it seeding refuses to run
without them).

`DEBUG_LOGS=1` streams both servers' logs into an in-browser console (Ctrl+`),
in development only — it exposes raw logs, so never outside your machine.
