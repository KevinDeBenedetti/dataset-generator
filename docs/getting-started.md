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

# 2. Build and start the stack
make dev     # builds if needed, starts, and streams logs (Ctrl-C stops it)
```

`make dev` runs in the foreground with `--watch`: images rebuild automatically
when dependencies change, and source edits hot-reload without a rebuild — so the
same command works on the first run and every day after.

Services started by Docker Compose:

| Service    | Role                                         | Host port                       |
| ---------- | -------------------------------------------- | ------------------------------- |
| `next`     | Web UI (Next.js)                             | `NEXT_PORT` (default `3000`)    |
| `server`   | REST API (FastAPI)                           | `SERVER_PORT` (default `8000`)  |

Ports are driven entirely by `.env` — set `NEXT_PORT` / `SERVER_PORT` (and point
`NEXT_PUBLIC_API_BASE_URL` at the API's host port) when the defaults collide with
another local stack. `make dev` prints the resolved URLs once every service is
healthy, so use those rather than assuming the defaults.

## Generate a dataset

From the UI, open the **Generate** page and pick a source:

- **File** — upload a PDF/image, transcribed by the configured vision model (`OPENAI_VLM_MODEL`)
- **GitHub** — fetch the READMEs and top-level docs of an account's public repositories

Or via the API (replace the port with your `SERVER_PORT` if you changed it):

```bash
curl -X POST http://localhost:8000/dataset/generate/github \
  -H "Content-Type: application/json" \
  -d '{
    "github_username": "octocat",
    "dataset_name": "example_docs"
  }'
```

Each page/document goes through the same pipeline: read/transcribe → clean →
QA generation → deduplication → save (a new version).

## Exporting to Hugging Face

Set `HF_TOKEN` (a token with write access) in `.env`, then use **Export to
Hugging Face** on a dataset's page — or call it directly:

```bash
curl -X POST http://localhost:8000/dataset/my-dataset/export/huggingface
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
