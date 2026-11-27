---
title: "2. Users sign in with a Hugging Face token, the admin from deployment secrets"
---

# 2. Users sign in with a Hugging Face token, the admin from deployment secrets

## Context

Every user publishes to the Hub with their own Hugging Face token, so the app
already needs one per user. On top of it, users signed in through Infomaniak
or GitHub SSO, or with a password, with email verification and an
`ADMIN_EMAILS` list deciding who was an admin: several identity systems for one
identity that matters, the Hub account.

Alternatives considered: keeping SSO and passwords; "Sign in with Hugging
Face" through OAuth only.

## Decision

- A user signs in with their Hugging Face username and token. The server
  verifies the token with `whoami`, checks that it belongs to that username,
  and stores it encrypted as the user's HF secret.
- Who may sign up is an admin policy: closed, any HF account, or members of
  listed HF organisations.
- The admin signs in only with deployment secrets: `ADMIN_USERNAME`,
  `ADMIN_PASSWORD_HASH` and an optional TOTP secret. No admin account lives in
  the database, and admin keys come from the environment.
- Infomaniak/GitHub SSO, password users, email verification and
  `ADMIN_EMAILS` are retired; existing accounts move to HF identities.
- HF OAuth is kept as a later alternative next to the token form
  ([#321](https://github.com/KevinDeBenedetti/dataset-generator/issues/321)).

## Consequences

- One identity per user, the one the app publishes with; a revoked token ends
  the user's sessions (stored tokens are re-checked).
- No mail delivery and no password reset flow to maintain for users.
- Admin access needs access to the deployment, which is deliberate; losing the
  secrets means redeploying with new ones.

Governs: [#298](https://github.com/KevinDeBenedetti/dataset-generator/issues/298), [#299](https://github.com/KevinDeBenedetti/dataset-generator/issues/299), [#300](https://github.com/KevinDeBenedetti/dataset-generator/issues/300), [#301](https://github.com/KevinDeBenedetti/dataset-generator/issues/301),
[#302](https://github.com/KevinDeBenedetti/dataset-generator/issues/302), [#321](https://github.com/KevinDeBenedetti/dataset-generator/issues/321).
