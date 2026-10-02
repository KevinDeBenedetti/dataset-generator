# Getting Started

Dataset Generator mines uploaded files or GitHub repositories and turns
them into question/answer datasets via LLMs, with versioned storage and
multi-format export.

## Prerequisites

- Docker Desktop (the stack runs with Docker Compose)
- An OpenAI-compatible API key for the LLM calls


Datasets, their Q/A pairs and their version history live in the PostgreSQL that
`make dev` starts — no external service to configure. Set `PERSIST_DATASETS=false`
to make generation a pass-through instead (the pairs come back in the API
response and nothing is stored).

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

| Service    | Role                                         | Host port                       |
| ---------- | -------------------------------------------- | ------------------------------- |
| `next`     | Web UI (Next.js)                             | `NEXT_PORT` (default `3020`)    |
| `server`   | REST API (FastAPI)                           | `SERVER_PORT` (default `8020`)  |
| `worker`   | Runs the queued dataset jobs                 | —                               |

Set `NEXT_PORT` / `SERVER_PORT` in `.env` when the defaults collide with another
local stack: compose derives the browser's API URL and the SSO callbacks from
them. `make dev` prints the resolved URLs once every service is healthy.

## Generate a dataset

From the UI, open the **Generate** page and pick a source:

- **File** — upload a PDF/image, transcribed page by page by the vision model
- **Web page** — one public URL (no crawling), reduced to text and cleaned

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
    "dataset_name": "example_docs",
    "model_qa": "claude:claude-sonnet-5"
  }'
```

Recurring sources — your GitHub profile and repos, the knowledge corpus — are
**jobs** (`apps/server/jobs/registry.py`): they run on their GitHub Actions
schedule and on demand from the **Jobs** page. There, **GitHub personal Q&A**
works in three steps: *Generate draft* runs in the background (progress shown,
you can leave the page), you review the new pairs and those held out for
review, then *Publish to Hugging Face* pushes exactly that draft to
`HF_QA_DATASET_REPO` — nothing is regenerated. API: `POST /jobs/{id}/run`,
`GET /jobs/runs/{run_id}`, `POST /jobs/runs/{run_id}/publish`.

Each page/document goes through the same pipeline: read/transcribe → clean →
QA generation → deduplication → save (a new version).

## Exporting to Hugging Face

Set `HF_TOKEN` (a token with write access) in `.env`, then use **Export to
Hugging Face** on a dataset's page — or call it directly:

```bash
curl -X POST http://localhost:8020/dataset/my-dataset/export/huggingface
```

The dataset repo is always created **private**. If a repo with that id already
exists and is public, the export is refused rather than publishing your data.

## Useful commands

```bash
make help       # list every target with its description
make dev        # start the stack (foreground, live logs)
make down       # stop and remove the containers
make reset      # purge the venv/node_modules volumes and rebuild (after a dependency change)
make logs       # stream logs from all containers
make clean      # remove containers, caches, lockfiles and virtualenvs
make dev-local  # run the API alone with uvicorn --reload, no Docker
make test       # run the test suite with an HTML coverage report
```

## Going further

- [Project README](https://github.com/KevinDeBenedetti/dataset-generator#readme) —
  architecture, features, authentication and full configuration reference
