---
title: Datasets on Hugging Face
---

# Datasets on Hugging Face

The **Datasets** section shows the datasets of your Hugging Face account. The
app keeps no copy of them: every page is read from the Hub with your own token,
at one precise commit. Generated data that is not published yet is listed under
**Drafts** instead (see [Getting Started](./getting-started.md)).

## The list

The list shows the dataset repos of the namespace saved in **Settings**, or of
your token's account when none is saved, private repos included. When your
token belongs to organizations, a menu switches to one of them.

Search matches the name, description and tags. The list filters on visibility
(all, private, public) and sorts by last update, name, downloads, likes or size.

## A dataset's page

| Tab        | What it shows                                                                                                                                                                                      |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Data       | The rows of a split, 25, 50 or 100 per page. Search covers every text field, nested ones included. Filters, sorting by column, Q/A datasets shown as cards. A click opens the whole row.           |
| Card       | The README rendered, then its metadata. Raw HTML is not rendered and images become links.                                                                                                          |
| Statistics | Per column: type, empty cells, value counts for label-like columns, histograms of text lengths, list sizes and numbers. Click a value to see its rows. Q/A datasets also count repeated questions. |
| Files      | Every file with its size and the split it feeds, with links to the Hub.                                                                                                                            |
| History    | Every commit is a version. **Browse** shows the data as of that commit; **Changes** compares it with the previous one, row by row.                                                                 |

In the row panel, `←` and `→` move to the previous or next row and `Esc`
closes it. Filters accept `is`, `is not`, `contains`, `<`, `≤`, `>`, `≥`,
`is empty` and `is not empty`, depending on the column's type.

The view lives in the URL (tab, version, split, search, filters, page, open
row): copy the address to share exactly what you see.

### Q/A datasets

A split is shown as Q/A cards when it has a question column (`question`,
`query`, `prompt`, `instruction` or `q`) and an answer column (`answer`,
`response`, `output`, `completion` or `a`). A `context`, `source_text` or
`passage` column is shown under the answer.

### Comparing versions

**Changes** matches rows by their `id` column when every row of both versions
has a unique one: an edited answer then counts as *changed*. Without such a
column, rows are matched by content, so an edit counts as one removal plus one
addition. The first 20 rows of each kind are listed.

## How splits are found

1. The `configs` block of the card's YAML header, when it has one.
2. Otherwise the Hub's naming rules: a file or folder named `train`/`training`,
   `validation`/`valid`/`val`/`dev` or `test`/`testing`/`eval`/`evaluation` feeds
   that split.
3. Otherwise every data file of the most common format forms the `train` split.

The viewer reads JSONL, JSON, CSV, TSV and Parquet. A JSONL, CSV, TSV or
Parquet file outside every split, such as the `review.jsonl` the GitHub job
holds out for review, is offered as an extra split.

## Limits

| Limit                               | Value                                    | Setting (`apps/server/core/config.py`) |
| ----------------------------------- | ---------------------------------------- | -------------------------------------- |
| Largest split the viewer loads      | 50 MB of data files (else: open the Hub) | `max_hub_view_bytes`                   |
| Loaded splits kept in memory        | 256 MB in total, per commit              | `hub_cache_bytes`                      |
| Reuse of a revision → commit lookup | 30 seconds, per token                    | `hub_resolve_ttl_seconds`              |
| Text cell in a page of rows         | 5,000 characters (the row panel: all)    | `MAX_CELL_CHARS` (`services/hub.py`)   |
| Versions listed                     | The 100 most recent commits              | `MAX_COMMITS` (`services/hub.py`)      |

::: tip Why the app reads the files itself
The Hub's own dataset viewer API serves private datasets only to PRO accounts
and Enterprise organizations
([dataset viewer docs](https://huggingface.co/docs/dataset-viewer/quick_start)),
and every dataset this app publishes is private.
:::

## API

Every route reads with the caller's own Hugging Face token, so the Hub decides
what each user sees: a repo the token can't read answers 404, like an unknown
one.

| Route                                         | Returns                                                   |
| --------------------------------------------- | --------------------------------------------------------- |
| `GET /hub/datasets`                           | The dataset repos of one of your namespaces (`author`)    |
| `GET /hub/datasets/{owner}/{name}`            | Metadata, card, files, splits and refs at one commit      |
| `GET /hub/datasets/{owner}/{name}/rows`       | A page of rows, with search, filters and sort             |
| `GET /hub/datasets/{owner}/{name}/row`        | One row in full (`row_idx`)                               |
| `GET /hub/datasets/{owner}/{name}/statistics` | The per-column statistics of a split                      |
| `GET /hub/datasets/{owner}/{name}/commits`    | The versions, newest first                                |
| `GET /hub/datasets/{owner}/{name}/compare`    | Rows added, removed and changed between `base` and `head` |

`rows` takes `revision`, `config`, `split`, `offset`, `length` (up to 100), `q`,
`filters`, `sort` and `order`. `filters` is a JSON list:

```json
[{ "column": "category", "op": "eq", "value": "docs" }, { "column": "confidence", "op": "gte", "value": 0.5 }]
```

Errors: `503` without a Hugging Face token, `404` for an unknown repo, revision,
split or row, `413` for a split above the size limit, `400` for a filter or
sort that doesn't apply, `422` for data files that don't read as a table, `502`
when the Hub fails.
