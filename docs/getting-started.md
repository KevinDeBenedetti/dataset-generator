# Getting Started

Dataset Generator scrapes web content, files or GitHub repositories and turns
them into question/answer datasets via LLMs, with Langfuse versioning and
multi-format export.

## Prerequisites

- Docker Desktop (the stack runs with Docker Compose)
- An OpenAI-compatible API key for the LLM calls
- Langfuse keys (`LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`)
  — **required**, not optional: Langfuse is the sole store for datasets, there
  is no local fallback table. Without it, generation still returns its pairs in
  the API response but nothing is persisted, and every dataset/Q&A read endpoint
  answers `503`.

## Setup

```bash
# 1. Configure environment variables
cp .env.example .env
# Edit .env with your API keys (OPENAI_*, LANGFUSE_*, …)

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
| `crawl4ai` | Headless page rendering used by the crawler  | internal only                   |

Ports are driven entirely by `.env` — set `NEXT_PORT` / `SERVER_PORT` (and point
`NEXT_PUBLIC_API_BASE_URL` at the API's host port) when the defaults collide with
another local stack. `make dev` prints the resolved URLs once every service is
healthy, so use those rather than assuming the defaults.

## Generate a dataset

From the UI, open the **Generate** page and pick a source:

- **URL** — scrape a single page or crawl a whole site (see [Crawling](./crawling.md))
- **File** — upload a PDF/image, transcribed by the configured vision model (`OPENAI_VLM_MODEL`)
- **GitHub** — fetch the READMEs and top-level docs of an account's public repositories

Or via the API (replace the port with your `SERVER_PORT` if you changed it):

```bash
curl -X POST http://localhost:8000/dataset/generate \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/docs",
    "dataset_name": "example_docs",
    "crawl": true
  }'
```

Each page goes through the same pipeline: scrape → clean → QA generation →
deduplication → Langfuse sync.

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

- [Crawling — configuration & fonctionnement](./crawling.md) — env vars,
  per-request overrides, BFS traversal and tuning
- [Project README](https://github.com/KevinDeBenedetti/dataset-generator#readme) —
  architecture, features, authentication and full configuration reference
