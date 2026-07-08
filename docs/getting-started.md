# Getting Started

Dataset Generator scrapes web content, files or GitHub repositories and turns
them into question/answer datasets via LLMs, with Langfuse versioning and
multi-format export.

## Prerequisites

- Docker Desktop (the stack runs with Docker Compose)
- An OpenAI-compatible API key for the LLM calls
- Optional: Langfuse keys for dataset versioning

## Setup

```bash
# 1. Configure environment variables
cp .env.example .env
# Edit .env with your API keys (OPENAI_*, LANGFUSE_*, …)

# 2. Build and start the stack
make dev     # clean + build + start (first run)
make start   # daily start, no rebuild
```

Services started by Docker Compose:

| Service    | Role                                         | Default URL             |
| ---------- | -------------------------------------------- | ----------------------- |
| `next`     | Web UI (Next.js)                             | `http://localhost:3000` |
| `server`   | REST API (FastAPI)                           | `http://localhost:8000` |
| `crawl4ai` | Headless page rendering used by the crawler  | internal only           |

## Generate a dataset

From the UI, open the **Generate** page and pick a source:

- **URL** — scrape a single page or crawl a whole site (see [Crawling](./crawling.md))
- **File** — upload a PDF/image, transcribed by the configured vision model (`OPENAI_VLM_MODEL`)
- **GitHub** — fetch the READMEs and top-level docs of an account's public repositories

Or via the API:

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
make start        # start without rebuild
make stop         # stop services
make build-cache  # rebuild after dependency changes
make rebuild      # full clean rebuild
docker compose logs -f
```

## Going further

- [Crawling — configuration & fonctionnement](./crawling.md) — env vars,
  per-request overrides, BFS traversal and tuning
- [Project README](https://github.com/KevinDeBenedetti/dataset-generator#readme) —
  architecture, features, authentication and full configuration reference
