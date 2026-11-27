---
title: Storage
---

# Storage

Published datasets live on Hugging Face, the source of truth: the **Datasets**
section reads them from the Hub with each user's own token, loading a split of at
most 50 MB, cached per commit (see [Datasets on Hugging Face](./datasets.md)).
Hugging Face exports are always **private** repos — an export into an existing
repo the Hub does not confirm private is refused; an import reads at most 50 MB
of data files, from a repo of at most 5,000 files and folders. A file or web
page draft reads its dataset's rows, review list, manifest and card (50 MB at
most together), each file once per commit: counted when the draft is made, read
again at publication only if the dataset changed meanwhile.

PostgreSQL is the only database (`postgres://` / `postgresql://` URLs are
accepted). Drafts — generated, not yet published — live in three tables:
`datasets`, `qa_pairs` (keyed by `(dataset_id, content hash)`, so re-running a
generation is idempotent) and `dataset_runs` (one numbered version per
generation). `PERSIST_DATASETS=false` makes generation a pass-through (also per
request: `persist`).

[Vector collections](./collections.md) keep their definition and state in the
`vector_collections` table, and their vectors in Qdrant only, in a collection
named after the row's id (`QDRANT_COLLECTION_PREFIX` + `c_` + id).

## Tabular drafts

Data sources, recipes, reviews and publications are rows of `data_sources`,
`recipes`, `reviews` and `publications`, each owned by a user (another user's id
answers 404). A recipe run is a `job_runs` row with `job_id="recipe"` and
`options.recipe_id`; its draft metadata (schema, profile, quality report,
provenance, row count) is in `job_runs.draft`. The rows themselves are never in
Postgres: they are a Parquet file in the **draft store**, a directory set by
`DRAFT_STORE_URL` (`file:///data/drafts` by default, the `drafts` volume of
`docker-compose.yml`):

```text
<owner_id>/<run_id>/data.parquet       the draft's rows
<owner_id>/<run_id>/raw/<file>         what the connector fetched
<owner_id>/sources/<data_source_id>/   an uploaded data source's file
```

Only `file:///` directories are supported: in production, mount a persistent
volume there on the API and the worker (both read and write it). A user holds
at most `QUOTA_DRAFT_BYTES_PER_USER` bytes (2 GB by default), checked before a
fetch and after the engine writes. Every hour the worker deletes the folders of
runs that are gone, published, failed or cancelled, or older than
`DRAFT_RETENTION_DAYS` (14 by default); deleting a recipe deletes its runs'
folders, deleting a data source its upload, deleting an account all of its
files. The account export lists data sources and recipes, never draft files.

The engine (`apps/server/engine`, [ADR 3](./adr/0003-duckdb-tabular-engine.md))
opens one DuckDB connection per run, confined to the run's folder
(`allowed_directories`, `enable_external_access=false`, configuration locked,
no extension installed or loaded at runtime), bounded by `ENGINE_MEMORY_LIMIT`,
`ENGINE_THREADS` and `ENGINE_TIMEOUT_S`. It loads the fetched files as one typed
table — text columns keep their text when a value has leading zeros or
thousands separators; Excel sheets are read with openpyxl — writes
`data.parquet` (ZSTD) and a profile per column (missing values, distinct
count, min, max, mean, standard deviation, top 10 values, samples).
