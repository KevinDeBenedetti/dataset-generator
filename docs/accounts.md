---
title: Accounts, roles and keys
---

# Accounts, roles and keys

## Sign-in and roles

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
limits hold across replicas. Deleting the account from **Settings → Your data**
needs a sign-in from the last 10 minutes: a stolen session alone can't do it.

In development, email/password sign-in is on too; see
[Configuration](./configuration.md) for the dev accounts and the switches that
depend on `ENVIRONMENT`.

## Backoffice (admins)

`/admin` — accounts, audit log, usage, platform switches. Admins see accounts and
*counts* (datasets, pairs, runs, which kinds of keys are saved), never dataset
content, settings values or keys. They change roles, disable (immediate sign-out)
and delete accounts (with their data; their Hugging Face repos stay). The
**Platform** tab holds the switches that used to be env vars: open sign-up,
allowed email domains, the OpenAI-compatible hosts users may use, any public
endpoint. Outside development sign-up starts closed: open it there once the
deployment is ready (`ADMIN_EMAILS` can always sign up). Every user can export
their data and delete their account from **Settings → Your data**.

## Per-user data and keys

Every dataset, run, model default and quality-rule set belongs to a user;
another user's resource answers **404**. `tests/api/test_tenant_isolation.py` walks
every route and fails on any new one it can't classify.

Each user enters their own OpenAI key, Hugging Face token and GitHub details in
**Settings** (and, in development, a Claude token). Secrets are encrypted at rest
(AES-256-GCM, bound to the user and the kind), checked against their provider
when saved, and **write-only**: no route returns one. Calls to a user-chosen
endpoint go through `core/net.py` (https, public addresses only, pinned
connection, no redirects). The key ring that encrypts them is described in
[Production](./production.md).

Upgrading a single-user install: existing data goes to the oldest admin, or to an
inactive `system` account until `python -m server.cli claim-legacy --email you@example.com`
(or the first sign-in of an `ADMIN_EMAILS` account) takes it.
