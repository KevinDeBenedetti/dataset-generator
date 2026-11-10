---
title: Production
---

# Production

The variables, and what `ENVIRONMENT` decides, are in
[Configuration](./configuration.md).

## One public host

The ingress sends `/api/*` to the API (prefix stripped) and the rest to Next.
Set `FRONTEND_URL=https://<host>`; the API is then `https://<host>/api`
(override with `API_PUBLIC_URL`), the SSO callbacks to register are
`https://<host>/api/auth/infomaniak/callback` and
`https://<host>/api/auth/github/callback`, and there is no CORS to configure.
Behind a proxy set uvicorn's `FORWARDED_ALLOW_IPS` so rate limits see the client
address. Health: `GET /health` (liveness, no database) and `GET /ready` (Postgres).
With `RUN_MIGRATIONS_ON_STARTUP=false`, migrations are left to a deployment step
(they run under a Postgres advisory lock either way).

## Encryption keys

`SECRETS_ENCRYPTION_KEYS` encrypts the keys users store: generate an entry with
`python -m server.cli gen-key`, and **back it up apart from the database** —
losing it means every user re-enters their keys. Rotate by prepending a new key,
running `python -m server.cli rewrap-secrets`, then dropping the old one.

## Images and deployment

`.github/workflows/images.yml` builds the production images (`target: prod`) and
publishes them to GHCR: `ghcr.io/<owner>/dataset-generator-server` (the API **and**
the job worker — same image, the worker just runs `python -m server.worker`) and
`ghcr.io/<owner>/dataset-generator-next`. A release (the release-please PR merged
on `main`) makes `ci-cd.yml` call it to produce `:vX.Y.Z` and `:latest`, as does a
`v*` tag pushed by hand; a manual run from `main` tags `:sha-<short>`, or rebuilds
a release with `gh workflow run images.yml -f tag=vX.Y.Z`. Nothing is built from
other branches, and a tag that is not on `main` is refused. amd64 only unless the
`IMAGE_PLATFORMS` repository variable says otherwise (`linux/amd64,linux/arm64`).
A release is only deployable once that workflow is green — a tag without an image
leaves the deployment's migration Job in `ImagePullBackOff`. Each image gets a
signed SLSA provenance attestation, stored by GitHub rather than in the registry:

```sh
gh attestation verify oci://ghcr.io/<owner>/dataset-generator-server:vX.Y.Z -R <owner>/dataset-generator
```

What a deployment runs, from the server image:

| Workload      | Command                                              | Probes                                         |
| ------------- | ---------------------------------------------------- | ---------------------------------------------- |
| API           | *(image default)* uvicorn, `WEB_CONCURRENCY` workers | liveness `GET /health`, readiness `GET /ready` |
| Worker        | `python -m server.worker`                            | — (drains on SIGTERM)                          |
| Migration Job | `python -m server.cli migrate`                       | runs once per release, before the pods roll    |

Set `RUN_MIGRATIONS_ON_STARTUP=false` on the API and the worker when a Job migrates.
Containers run as uid 10001 and need no writable root filesystem.
`HF_HUB_OFFLINE` must stay unset (uploads and token checks need the Hub). Leave
`ENVIRONMENT` unset (= production), and do not set `ALLOW_ENV_CREDENTIALS`: it
no longer exists — production lends the server's keys for one thing only. With `SERVER_LLM_FOR_ADMINS=true`, admins who saved no
OpenAI-compatible key of their own call `OPENAI_BASE_URL` with
`OPENAI_API_KEY`: point them at a gateway you run (an in-cluster
`http://…:4000/v1` LiteLLM Service is fine) with a virtual key of its own, so
its budget and revocation stay in the gateway. Other users always bring their
own key.

Required in the deployment's secrets/config: `DATABASE_URL`, `AUTH_SECRET_KEY`,
`SECRETS_ENCRYPTION_KEYS`, `FRONTEND_URL` (https), and at least one SSO pair
(`INFOMANIAK_CLIENT_ID`/`SECRET` or `GITHUB_CLIENT_ID`/`SECRET`); recommended:
`ADMIN_EMAILS`, `REDIS_URL`, `FORWARDED_ALLOW_IPS`. The Next image
needs only `API_INTERNAL_URL` (the API's in-cluster URL).

[Vector collections](./collections.md) are off until the API and the worker get
`QDRANT_URL` (and `QDRANT_API_KEY`); they embed on the users' endpoints, so
nothing more is needed.
