---
title: Getting Started
---

# Getting Started

Dataset Generator mines uploaded files, web pages or GitHub repositories and
turns them into question/answer datasets via LLMs. Hugging Face is the source of
truth: a dataset is generated as a draft, reviewed, then published to the Hub,
where the app reads it back.

## Prerequisites

- Docker Desktop (the stack runs with Docker Compose)
- An OpenAI-compatible API key for the LLM calls
- A Hugging Face access token with write access, to publish datasets and
  browse them in the **Datasets** section

Where the data lives:

| Data                   | Store                                       | Shown in     |
| ---------------------- | ------------------------------------------- | ------------ |
| Drafts (not published) | The PostgreSQL that `make dev` starts       | **Drafts**   |
| Published datasets     | Your Hugging Face account, as private repos | **Datasets** |

Set `PERSIST_DATASETS=false` to make generation a pass-through instead (the
pairs come back in the API response and no draft is stored).

## Setup

```bash
# 1. Configure environment variables
cp .env.example .env
# Edit .env with your API keys (OPENAI_*, …)
# An older .env needs ENVIRONMENT=development added: without it (or a real
# AUTH_SECRET_KEY) the API refuses to start.

# 2. Build and start the stack
make dev     # builds if needed, starts, and streams logs (Ctrl-C stops it)
```

`make dev` runs in the foreground with `--watch`: images rebuild automatically
when dependencies change, and source edits hot-reload without a rebuild — so the
same command works on the first run and every day after.

Services started by Docker Compose:

| Service  | Role                         | Host port                      |
| -------- | ---------------------------- | ------------------------------ |
| `next`   | Web UI (Next.js)             | `NEXT_PORT` (default `3020`)   |
| `server` | REST API (FastAPI)           | `SERVER_PORT` (default `8020`) |
| `worker` | Runs the queued dataset jobs | —                              |

Set `NEXT_PORT` / `SERVER_PORT` in `.env` when the defaults collide with another
local stack: compose derives the browser's API URL and the SSO callbacks from
them. `make dev` prints the resolved URLs once every service is healthy.
Every host port is bound to `127.0.0.1`: the stack is not reachable from your
network.

## Generate a dataset

From the UI, open the **Generate** page, name the Hugging Face dataset the
pairs go to (an existing one or a new one), and pick a source:

- **File** — upload a PDF/image (up to 20 MB and 50 pages), transcribed page
  by page by the vision model
- **Web page** — one public URL (no crawling), reduced to text and cleaned

The pairs become a draft listed under **Drafts**: nothing reaches Hugging Face
before you review it. A dataset's page offers **Add data**, which opens this
form with that dataset filled in.

Each step's model (cleaning, Q&A, vision) defaults to what is set on the
**Models** page and can be overridden per generation. A model is a
`"<provider>:<model>"` reference: `openai:…` (OpenAI-compatible API, on the key
saved in **Settings**) or, in local development and CI only, `claude:…` (Claude
subscription through the Claude Agent SDK, a token from `claude setup-token`).

Or via the API (replace the port with your `SERVER_PORT` if you changed it):

```bash
curl -X POST http://localhost:8020/dataset/generate/url \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://docs.example.com/guide",
    "dataset_name": "Example docs",
    "target_repo": "your-namespace/example-docs",
    "model_qa": "claude:claude-sonnet-5-5"
  }'
```

The response's `draft_run_id` is the draft to review.

To build a dataset from chosen GitHub repos, README and `docs/` files, use a
recipe on the **GitHub** page: see [GitHub datasets](./github.md).

Datasets built from your whole GitHub account — your profile and repos, the
knowledge corpus — are **jobs** (`apps/server/jobs/registry.py`), started on
demand from the same page. There, **GitHub personal Q&A** works in three
steps: *Generate draft* runs in the background (progress shown, you can leave
the page), you review the new pairs and those held out for review, then
*Publish to Hugging Face* pushes exactly that draft to the Q&A dataset repo
saved in **Settings** — nothing is regenerated. API: `POST /jobs/{id}/run`,
`GET /jobs/runs/{run_id}`, `POST /jobs/runs/{run_id}/publish`.

Each page/document goes through the same pipeline: read/transcribe → clean →
QA generation → deduplication → save (a new version of the draft).

## Publishing to Hugging Face

Add your Hugging Face token (write access) in **Settings**, open the draft
under **Drafts**, review it — leave pairs out, edit a question or an answer —
then use **Publish to Hugging Face**. The reviewed pairs are merged into the
dataset's `data/train.jsonl` by id, in one commit with its card. API:
`GET /jobs/drafts`, `GET /jobs/runs/{run_id}` and
`POST /jobs/runs/{run_id}/publish` (`exclude`, `edits`).

Local drafts generated before this review existed stay under **Drafts** until a
later release: publish each one (**Publish to Hugging Face**, or
`POST /dataset/{name}/export/huggingface`) or delete it.

The dataset repo is always created **private**. If a repo with that id already
exists and the Hub does not confirm it is private, publishing is refused rather
than making your data public. Once published, the dataset appears under
**Datasets**, read from the Hub: see [Datasets on Hugging Face](./datasets.md).
**Import from Hugging Face** (on the **Quality control** page) reads at most
50 MB of data files per repo, from a repo of at most 5,000 files and folders.

## Useful commands

```bash
make help       # list every target with its description
make dev        # start the stack (foreground, live logs)
make down       # stop and remove the containers
make reset      # delete every volume (the database included) and rebuild
make logs       # stream logs from all containers
make clean      # remove containers, caches, lockfiles and virtualenvs
make dev-local  # run the API alone with uvicorn --reload, no Docker
make test       # run the test suite with an HTML coverage report
```

::: warning A front-end dependency changed
`/app/node_modules` lives in the `next_node_modules` volume, which outlives image
rebuilds, so the `next` container installs the packages of `bun.lock` each time
it starts. If a page still reports `Module not found` after a dependency change,
restart that container, the database stays untouched:

```sh
docker compose restart next
```

Images built before this start-up install don't have it: run
`docker compose exec next bun install` once, then the restart above.
:::

## Going further

- [Datasets on Hugging Face](./datasets.md) — browsing, statistics and versions
  of the published datasets
- [GitHub datasets](./github.md) — your whole account, or a recipe choosing the
  GitHub sources of a dataset
- [Vector collections](./collections.md) — embedding a split into Qdrant,
  searching it and testing its retrieval
- [Configuration](./configuration.md) — `.env`, what `ENVIRONMENT` decides, the
  local stack's ports and dev accounts
- [Production](./production.md) — one public host, encryption keys, images and
  deployment
- [Accounts, roles and keys](./accounts.md) — SSO sign-in, admins, per-user keys
- [Jobs](./jobs.md) and [Storage](./storage.md) — the worker, quotas, where the
  data lives
- [Development](./development.md) — tests, git hooks, the API contract
