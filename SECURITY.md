# Security policy

Dataset Generator is a multi-user web application: it stores the API keys its
users save, fetches the pages they point it at and parses the files they
upload. A vulnerability can expose another user's keys or data, so reports are
welcome and treated as a priority.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through GitHub:
**Security → Report a vulnerability** on this repository (private
vulnerability reporting). Include the affected part (API server, web UI,
container images or workflows), the version (release tag or commit SHA) and,
if possible, a reproduction.

You can expect an acknowledgement within a few days. Fixes are released as a
new version; the advisory is published once a fixed release is available.

## Supported versions

Only the latest release receives fixes: run the newest
`ghcr.io/<owner>/dataset-generator-server` and `dataset-generator-next` images
(`:vX.Y.Z`).

## Scope

In scope: the code of this repository, the images it publishes and its GitHub
Actions workflows. Out of scope: the services it calls (an OpenAI-compatible
endpoint, Hugging Face, GitHub, Infomaniak) and the local development stack
(`make dev`). That stack runs with `ENVIRONMENT=development` on purpose —
seeded accounts with weak default passwords, the server's own keys used for
every user and, with `DEBUG_LOGS=1`, an unauthenticated log stream — and
listens on `127.0.0.1` only.

## Running it safely

- Leave `ENVIRONMENT` unset (production): the server then refuses to boot
  without `DATABASE_URL`, `SECRETS_ENCRYPTION_KEYS`, a real `AUTH_SECRET_KEY`,
  an https `FRONTEND_URL` and a sign-in method.
- Back up `SECRETS_ENCRYPTION_KEYS` apart from the database: it encrypts the
  keys users store (AES-256-GCM, bound to the user and the kind of key).
- Behind a reverse proxy, set `FORWARDED_ALLOW_IPS` to its address, or the
  login rate limits see the proxy instead of the client.
- Never set `DEBUG_LOGS` outside your machine.
- Sign-up starts closed outside development: open it from the backoffice
  **Platform** tab once the deployment is ready.
- Check an image's build provenance before deploying it:
  `gh attestation verify oci://ghcr.io/<owner>/dataset-generator-server:vX.Y.Z -R <owner>/dataset-generator`.

## Hardening in this repository

Requests to user-chosen URLs only reach public addresses, over a connection
pinned to the address that was checked (`apps/server/core/net.py`). Uploads and
request bodies are size-capped. Every API route outside `/auth`, the health
probes and the root requires a session, and another user's resource answers
404. The CI audits both lockfiles (bun audit, pip-audit), runs CodeQL and a
secret scan, reviews the dependencies a pull request adds and pins every
third-party action by commit SHA; images carry a signed SLSA build provenance
attestation.

### Repository settings (maintainer checklist)

These live outside the code and must be set in the repository settings:

- [ ] **Private vulnerability reporting** enabled.
- [ ] **Dependabot alerts** and **Dependabot security updates** enabled.
- [ ] **Code scanning**: CodeQL *default setup* off. `ci-cd.yml` uploads its
      own analysis (advanced setup), which GitHub rejects while default setup
      is on.
- [ ] **Branch ruleset on `main`**: require a pull request and the CI checks;
      block force pushes and deletion.
- [ ] **Tag ruleset on `v*.*.*`**: block updates and deletion — a release tag
      must keep pointing at the code its images were built from. The moving
      aliases (`v0`, `v0.N`) stay out of it: the release job updates them.
- [ ] Actions → workflow permissions: **read-only `GITHUB_TOKEN`** by default,
      with **Allow GitHub Actions to create and approve pull requests**
      (release-please opens its release PR with that token).
- [ ] Actions → **Require approval for all outside collaborators** on fork
      pull requests.
