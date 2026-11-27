---
title: Accounts, roles and keys
---

# Accounts, roles and keys

## Sign-in and roles

Users sign in with their **Hugging Face username and access token**
(`POST /auth/hf`). The server checks the token with the Hub's `whoami`: it must
belong to that username (any case) and be able to write to the user's own
namespace — a `write` token, or a fine-grained token with `repo.write` on the
user. A read token, another account's token, a revoked one and a malformed one
are each refused with their own message; a Hub outage answers 503 and refuses
nobody. The first sign-in creates the account when the sign-up policy allows
it; the account is keyed on the Hub's stable account id, so it survives a
renamed Hugging Face account. The token is stored encrypted as the user's
Hugging Face token (a different token replaces it: that is how it is rotated),
never returned by any route, never logged. Failures are throttled to 10 a
minute per IP and per username. The Hub's email is kept only when it is
verified and no other account has it: an account is never joined by email.

The stored token is checked again before every publication (a draft, a
scheduled publish, a corpus push; one `whoami` per token every 10 minutes at
most) and by the worker once a day (a batch of the tokens unchecked for 24 h,
every hour). A token the Hub rejects, or that lost write access, is refused
before anything is written and marks the account: an account that signs in
with its token is signed out everywhere, the user's schedules are skipped with
the reason "its owner's Hugging Face token no longer works", and the app shows
a banner until the token is replaced (signing in again with a new token does
it). A Hub outage during a check changes nothing.

Until they are retired, users can also sign in with **Infomaniak** (OpenID Connect) or **GitHub** (an OAuth App,
scopes `read:user user:email`); a provider is offered once its client id and
secret are set. Both flows use state + PKCE (S256) and, like the password form,
land on the page that sent you to the login (its `?from=`: a path of the app
only, checked again by the API), else on the dashboard. A sign-in is matched on the
provider's stable id (GitHub's numeric user id, never the login); it joins an
existing account only through a **verified** email, or when the signed-in user
links it from **Settings → Sign-in methods**. The last sign-in method can't be
removed; **Sign out everywhere** revokes every session at once.

Two roles, `user` and `admin`. The admin of the deployment signs in at
`/admin/login` (not linked from the public login page) with **deployment
secrets only**: `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` (argon2id, printed by
`python -m server.cli hash-password`) and, optionally, `ADMIN_TOTP_SECRET`
(base32, for an authenticator app). The account is created from them at server
start and can't be demoted, disabled or deleted in the app; changing
`ADMIN_USERNAME` makes a new admin and disables the previous one. A wrong
username, password or code all get the same 401; failures are throttled to 5 a
minute per IP and every attempt is in the audit log (`admin.login.success`,
`admin.login.failure`), never with the values typed. Rotating
`ADMIN_PASSWORD_HASH` refuses the old password at once; open sessions end with
**Sign out everywhere**. This admin acts with the server's own keys
(`ADMIN_HF_TOKEN`, else `HF_TOKEN`, and `OPENAI_*`, `GITHUB_*`): its Settings has
nothing to fill.

Until SSO is retired, verified emails listed in `ADMIN_EMAILS` are made admin at
sign-in too, may always sign up, and can't be demoted or disabled.

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
**Platform** tab holds the switches that used to be env vars: the sign-up
policy, the OpenAI-compatible hosts users may use, any public endpoint.

**Who can sign up** is applied at the first sign-in of a Hugging Face account
only (existing accounts are not re-checked):

| Value    | Meaning                                                                        |
| -------- | ------------------------------------------------------------------------------ |
| `closed` | Nobody new (the default outside development)                                   |
| `orgs`   | Only accounts that belong to one of the listed Hugging Face organisations      |
| `open`   | Any Hugging Face account with a valid write token (the default in development) |

The **allowed HF usernames** always pass (invitations). Membership is read from
the token's `whoami`: a fine-grained token needs the permission to read the
user's organisation memberships for `orgs` to see them. Every change is audited
with the values before and after. The admin of `ADMIN_USERNAME` is never subject
to the policy; an SSO sign-in can only create an account under `open`
(`ADMIN_EMAILS` can always sign up). Every user can export
their data and delete their account from **Settings → Your data**.

## Per-user data and keys

Every dataset, run, model default and quality-rule set belongs to a user;
another user's resource answers **404**. `tests/api/test_tenant_isolation.py` walks
every route and fails on any new one it can't classify.

Each user enters their own OpenAI-compatible key (and its base URL), Hugging
Face token and GitHub details in **Settings**. One exception, off unless the deployment sets
`SERVER_LLM_FOR_ADMINS=true`: an admin who saved no OpenAI-compatible key calls
the server's endpoint with the server's key — a gateway the operator runs, such
as LiteLLM (see [Configuration](./configuration.md)). The role is read at each
request and run, so a demoted admin loses it at once. Secrets are encrypted at rest
(AES-256-GCM, bound to the user and the kind), checked against their provider
when saved, and **write-only**: no route returns one. Calls to a user-chosen
endpoint go through `core/net.py` (https, public addresses only, pinned
connection, no redirects). The key ring that encrypts them is described in
[Production](./production.md).

Upgrading a single-user install: existing data goes to the oldest admin, or to an
inactive `system` account until `python -m server.cli claim-legacy` (to the
admin of `ADMIN_USERNAME`; `--email you@example.com` for another account), or the
first sign-in of an `ADMIN_EMAILS` account, takes it.
