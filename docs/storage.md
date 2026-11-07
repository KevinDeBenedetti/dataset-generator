---
title: Storage
---

# Storage

Published datasets live on Hugging Face, the source of truth: the **Datasets**
section reads them from the Hub with each user's own token, loading a split of at
most 50 MB, cached per commit (see [Datasets on Hugging Face](./datasets.md)).
Hugging Face exports are always **private** repos — an export into an existing
repo the Hub does not confirm private is refused; an import reads at most 50 MB
of data files.

PostgreSQL is the only database (`postgres://` / `postgresql://` URLs are
accepted). Drafts — generated, not yet published — live in three tables:
`datasets`, `qa_pairs` (keyed by `(dataset_id, content hash)`, so re-running a
generation is idempotent) and `dataset_runs` (one numbered version per
generation). `PERSIST_DATASETS=false` makes generation a pass-through (also per
request: `persist`).

[Vector collections](./collections.md) keep their definition and state in the
`vector_collections` table, and their vectors in Qdrant only, in a collection
named after the row's id (`QDRANT_COLLECTION_PREFIX` + `c_` + id).
