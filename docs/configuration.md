---
title: Configuration
---

# Configuration

Everything is configured through `.env` (copy `.env.example`). The file is
deliberately short: only what differs between deployments is a variable; tuning
values are constants in `apps/server/core/config.py`, and everything a
deployment can't get wrong follows from **`ENVIRONMENT`**.

| Setting                  | `ENVIRONMENT=development` (local)                             | anything else (production)                                                                                                                                     |
| ------------------------ | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Session cookies          | plain names, http                                             | `__Host-` prefixed, Secure (https only)                                                                                                                        |
| Sign-in                  | SSO + email/password; the admin also with `ADMIN_PASSWORD`    | SSO only (`ENABLE_LOCAL_LOGIN=true` to allow passwords); the admin with `ADMIN_USERNAME` + `ADMIN_PASSWORD_HASH` only                                          |
| Sign-up                  | open                                                          | closed until an admin opens it (backoffice **Platform** tab)                                                                                                   |
| Model keys               | a user's own, else the server's `OPENAI_API_KEY`, `HF_TOKEN`… | the user's own only; with `SERVER_LLM_FOR_ADMINS=true`, an admin without one uses the server's endpoint and key                                                |
| `/docs`, `/openapi.json` | on                                                            | off                                                                                                                                                            |
| Encryption key ring      | derived from `AUTH_SECRET_KEY`                                | `SECRETS_ENCRYPTION_KEYS` required                                                                                                                             |
| Startup checks           | none                                                          | refuses to boot without `DATABASE_URL`, `SECRETS_ENCRYPTION_KEYS`, a real `AUTH_SECRET_KEY`, an https `FRONTEND_URL`, a sign-in method and the admin's secrets |

What a production deployment sets, and how it is served, is in
[Production](./production.md); who can sign in, and with which keys, in
[Accounts, roles and keys](./accounts.md).

## Admin sign-in

The admin signs in at `/admin/login` with these secrets only (see
[Accounts, roles and keys](./accounts.md)).

| Variable              | What it sets                                                                                                |
| --------------------- | ----------------------------------------------------------------------------------------------------------- |
| `ADMIN_USERNAME`      | The admin's username: letters, digits, `.`, `_`, `-` (required outside development)                         |
| `ADMIN_PASSWORD_HASH` | Its password, as the argon2id hash `python -m server.cli hash-password` prints (required with the username) |
| `ADMIN_TOTP_SECRET`   | Optional: a base32 secret; the sign-in then asks for the authenticator app's 6-digit code                   |
| `ADMIN_PASSWORD`      | Development only: the password in clear, instead of the hash (production refuses to start with it)          |
| `ADMIN_HF_TOKEN`      | The admin's Hugging Face token (blank: `HF_TOKEN`); the admin's other keys are the server keys below        |

## Tabular drafts

See [Storage](./storage.md#tabular-drafts).

| Variable                     | What it sets                                                              |
| ---------------------------- | ------------------------------------------------------------------------- |
| `DRAFT_STORE_URL`            | The draft store's directory, `file:///…` (default `file:///data/drafts`)  |
| `QUOTA_DRAFT_BYTES_PER_USER` | Bytes of drafts and fetched files a user may hold (default 2 GB)          |
| `DRAFT_RETENTION_DAYS`       | Unpublished drafts older than this are deleted by the worker (default 14) |

## Models

Two models, both on an OpenAI-compatible endpoint (OpenAI itself, or a gateway
such as LiteLLM, vLLM or Ollama) reached with each user's own key and base URL,
saved in **Settings**: one LLM for every step, and one embedding model. The
deployment names them; on the **Models** page each user can pick another LLM,
among those configured and those their endpoint lists.

| Variable                  | What it sets                                                                                                                                               |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OPENAI_LLM_MODEL`        | The LLM of every step: cleaning, Q&A generation, scoring, the dataset jobs, and the transcription of uploaded PDF and image pages — so it must read images |
| `OPENAI_EMBEDDING_MODEL`  | The embedding model: the duplicate, grounding and coverage checks, and the first choice of a new collection                                                |
| `OPENAI_REASONING_EFFORT` | Sent to the LLM (default `low`); `off` for models that refuse the parameter                                                                                |
| `SERVER_LLM_FOR_ADMINS`   | Outside development: admins who saved no key call `OPENAI_BASE_URL` with `OPENAI_API_KEY` (other users bring their own)                                    |

A key and its endpoint always travel together: the server's key is only ever
sent to `OPENAI_BASE_URL`, and a user's key only to the base URL they saved
(OpenAI's when blank). The server's URL may be a private `http` address, such
as an in-cluster gateway: the operator set it. A URL a user types must be a
public `https` endpoint that the backoffice allows.

`OPENAI_EMBEDDING_MODEL` is the default embedding model. On the **Models** page,
each user can pick another of their endpoint's embedding models: **Measure and
use** embeds a built-in test set with it (short English and French texts about
a resume and software projects: rephrasings and look-alike questions, faithful
and wrong answers, covered and uncovered sections), puts each threshold where
it best separates them, and saves the model with its thresholds for every
check of that user's datasets. Each model scores on its own scale, so measure
the one you use: the defaults (constants in `apps/server/core/config.py`) were
measured on a small local model the server no longer runs.

Without an embedding model — none set, no endpoint, or one that can't embed
with it — the checks compare the words instead, and no collection can be
built.

A LiteLLM gateway, for example, with a virtual key and the aliases it serves:

```sh
OPENAI_BASE_URL=http://litellm:4000/v1
OPENAI_API_KEY=sk-...
OPENAI_LLM_MODEL=chat-default
OPENAI_EMBEDDING_MODEL=embed-default
```

## Server keys (development fallback)

In development, every key or setting a user hasn't saved in **Settings** comes
from these variables. Outside development they serve no user: each saves their
own, except the admin of `ADMIN_USERNAME`, who always acts with them, and an
admin with `SERVER_LLM_FOR_ADMINS=true` and no key of their own, who calls
`OPENAI_BASE_URL` with `OPENAI_API_KEY`.

| Variable                     | What it sets                                                               |
| ---------------------------- | -------------------------------------------------------------------------- |
| `OPENAI_API_KEY`             | The key of the OpenAI-compatible endpoint, sent only to `OPENAI_BASE_URL`  |
| `OPENAI_BASE_URL`            | That endpoint (blank: OpenAI's)                                            |
| `HF_TOKEN`                   | A Hugging Face token with write access; published repos are always private |
| `HF_NAMESPACE`               | Completes a bare repo name (blank: the token's own account)                |
| `HF_QA_DATASET_REPO`         | The GitHub Q&A dataset (`namespace/name` or `name`)                        |
| `HF_DATASET_REPO`            | The knowledge corpus (`namespace/name` or `name`)                          |
| `HF_QA_DATASET_LICENSE`      | The license written on the GitHub Q&A dataset's card, such as `cc-by-4.0`  |
| `HF_QA_DATASET_LICENSE_LINK` | With the license `other`: the link to its text                             |
| `GITHUB_USERNAME`            | The GitHub account the GitHub jobs read                                    |
| `GITHUB_TOKEN`               | Optional: only raises the GitHub API quota                                 |

The two license settings are the server's alone: a user can't save them.

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
(default `dataset_`) lets several deployments share one Qdrant, each with its
own prefix. The worker drops the collections under its prefix that none of
its rows names, once an hour; the first deployment to do so claims the prefix
(a `<prefix>claim` collection), and another one configured with the same
prefix then drops nothing and logs an error saying so.

The [Resume](./resume.md) page reads Reactive Resume with two server secrets:
`REACTIVE_RESUME_URL`, the instance's root (blank: rxresu.me), and
`REACTIVE_RESUME_API_KEY`, a key of your account there. Admins only.

After an admin's **Knowledge corpus** run has published, the server can tell
the site that indexes the corpus to read it again: it POSTs
`CORPUS_REINDEX_URL` with `CORPUS_REINDEX_SECRET` as a bearer token. Set both
or neither. Outside development the URL must be https, or http to an address
inside the network (a cluster Service such as `http://portfolio.portfolio.svc.cluster.local:3000/…`,
or a private IP): a server that would send the secret in clear to a public host
refuses to start. They are the operator's, so another user's run never calls the
URL; a site that is down is reported in the run, which stays published.

`make dev-local` runs the API outside Docker (on `127.0.0.1:8020`, the
`SERVER_PORT` the front-end and the SSO callbacks expect, with a worker
inside the process — the CPU-heavy steps run on their own threads, so its
heartbeats never wait behind them) against the compose Postgres through its
host port.

Dev accounts, seeded at startup by the local stack (`docker-compose.yml` sets
`SEED_DEV_USERS=true`; development only): `admin@example.com` /
`admin1234` and `user@example.com` / `user1234`. `DEV_ADMIN_PASSWORD` /
`DEV_USER_PASSWORD` in `.env` change them (72 bytes at most); outside
development, seeding refuses to run without them.

`DEBUG_LOGS=1` streams both servers' logs into an in-browser console (Ctrl+`),
in development only — it exposes raw logs, so never outside your machine.
