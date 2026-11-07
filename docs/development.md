---
title: Development
---

# Development

## Tests and coverage

The suite runs against a **real PostgreSQL instance**, started as a throwaway
container by [testcontainers](https://testcontainers-python.readthedocs.io/), so
a reachable Docker daemon is required. One container is shared by the whole
session and the schema is recreated around each test. To reuse an already-running
Postgres instead (and skip the container), point `TEST_DATABASE_URL` at it —
be aware the suite drops and recreates its tables there.

```sh
# Run tests with coverage (HTML report in htmlcov/index.html)
make test

# Run tests for CI (XML report, enforces 70% minimum)
make test-ci

# Run the git hooks (includes the tests on push)
uv run prek run --all-files
```

CI runs the suite with coverage on every push, printed in the job log; the job
fails below the threshold, **70%**.

## Git hooks

Hooks are managed by [prek](https://prek.j178.dev/) and declared in a single
`prek.toml` at the repo root — there is no `.pre-commit-config.yaml`. The shims
are installed by `make setup` (`uv run prek install`).

Two things keep the hooks honest with CI: the linters run through `uv run` /
`bun run`, so they use the versions already pinned in `pyproject.toml` and
`apps/next/package.json`; and everything prek ships natively (whitespace, EOF,
YAML/JSON/TOML syntax, private keys, …) uses `repo = "builtin"` — offline, no
environment to build, no `rev` to bump.

Three security hooks run too: gitleaks on the staged changes (the version CI
pins, reading `.gitleaks.toml`), and zizmor and actionlint on the GitHub
workflows.

```sh
uv run prek run --all-files      # every hook, every file
uv run prek run                  # staged files only
uv run prek run ruff             # a single hook
uv run prek run --stage pre-push # includes the test suite
uv run prek util list-builtins   # what "builtin" provides
```

`hadolint-docker` needs a running Docker daemon, and the `pytest` hook (pre-push
only) needs one too — the suite starts a throwaway Postgres.

## API schema and client

`apps/next/openapi.json` is the committed contract between the two apps. The
TypeScript client is **generated from it, never committed**: `apps/next/api/gen/`
is gitignored and rebuilt before every `bun run dev`, `build`, `typecheck` and
`test` (`pre*` scripts), like a dependency. The hand-written wrappers the app
actually imports (`api/sdk.ts`, `api/types.ts`) sit one level up.

```sh
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

## Dependencies

`make upgrade` rewrites both lockfiles within the declared constraints, skipping
releases younger than a week (`exclude-newer` in `pyproject.toml`,
`minimumReleaseAge` in `apps/next/bunfig.toml` — the same cooldown as
dependabot); review the diff, then `make lint test`. Each cap or skipped release
in `pyproject.toml` says why next to it: huggingface-hub stays below 2 until
fastembed allows it, and PyMuPDF skips 2.0, whose import costs seconds and
hundreds of megabytes in every process.
