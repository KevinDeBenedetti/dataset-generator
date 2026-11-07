---
title: Vector collections
---

# Vector collections

A **collection** is one split of one of your Hugging Face datasets, embedded
into [Qdrant](https://qdrant.tech/) so it can be searched by meaning. The
**Collections** page builds them, searches them and tests how well their
questions find their answers. The dataset stays on Hugging Face: a collection
holds vectors computed from it at one commit, and its definition.

## Build one

Open **Collections → New collection**, or **Build a collection** on a dataset's
page, then pick:

| Field                            | What it decides                                                                                                                           |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Dataset and split                | The rows embedded, read at the dataset's latest commit. A split over 50 MB is refused, as in the viewer.                                  |
| Text to embed                    | One to four text columns, joined by a blank line. A row empty in all of them is skipped.                                                  |
| Questions for the retrieval test | The column the test asks with. For a Q/A split, the question column.                                                                      |
| Embedding model                  | A local model: multilingual MiniLM (the app's own, built into the image), BGE small or base (English, tuned for retrieval), or MiniLM L6. |

The worker then reads the split with your own token and embeds every row on
its CPU: nothing is sent to a model provider. The page shows the progress; a
build can be cancelled. Each row becomes a point whose id is the row's position
in the split, and whose payload holds the embedded `text` and the row's text
`fields`.

A collection keeps the commit it was built from. Once the dataset has a newer
commit, its page says so and **Rebuild** embeds the new version, replacing the
vectors.

## Search it

**Search** embeds a query with the collection's model and lists the closest
rows, each with its cosine similarity and a link to the row in the dataset
viewer, at the commit the collection was built from.

## Test it

**Retrieval test** samples rows of the split (50 to 500). Each one asks with
its question column, and a hit is its own row coming back:

| Result               | Meaning                                                   |
| -------------------- | --------------------------------------------------------- |
| Found first          | Share of the rows whose own row is the top hit            |
| In the top k         | Share of the rows whose own row comes back at all         |
| Mean reciprocal rank | 1 when every row comes first, 0 when none is in the top k |

The rows not found first are listed with what came first instead. A top hit
with a similarity of 0.95 or more is flagged as a possible duplicate: the same
pair twice in the dataset.

::: tip Compare models and columns
The sample depends only on the split and its commit. Build two collections of
the same split, with another model or other columns, and they are tested on
the same rows.
:::

::: warning Embed the answers, ask with the questions
When the question column is embedded too, every question finds its own text
and the test is meaningless; the page says so. Embed the answer (and its
context) alone to measure retrieval.
:::

## Use it from your own code

**Use it** gives the collection's Qdrant name and a Python snippet that queries
it with `qdrant-client` and `fastembed`. Embed queries with the same model, and
with `query_embed`, as the build embedded the rows with `passage_embed`.

## Limits

- Qdrant must be configured: see [Configuration](./configuration.md). Without
  it the page says so and offers nothing to build.
- 20 collections per user, and one build at a time.
- Builds count towards the job quotas (`QUOTA_ACTIVE_RUNS`,
  `QUOTA_RUNS_PER_DAY`, see [Jobs](./jobs.md)).
- Deleting a collection drops its vectors; deleting your account drops all of
  them. The data export lists your collections, without their vectors.
