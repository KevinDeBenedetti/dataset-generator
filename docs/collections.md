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

| Field                            | What it decides                                                                                                                                                                       |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dataset and split                | The rows embedded, read at the dataset's latest commit. A split over 50 MB is refused, as in the viewer.                                                                              |
| Text to embed                    | One to four text columns, joined by a blank line. A row empty in all of them is skipped.                                                                                              |
| Questions for the retrieval test | The column the test asks with. For a Q/A split, the question column.                                                                                                                  |
| Embedding model                  | One of your OpenAI-compatible endpoint's embedding models: `OPENAI_EMBEDDING_MODEL` (the default), or another it serves. Without an endpoint that embeds, no collection can be built. |

The worker then reads the split with your own token and embeds every row on
your OpenAI-compatible endpoint (the model is named `openai:<id>`), with your
key: every row is sent there. The page shows the progress; a build can be
cancelled. Each row becomes a point whose id is the row's position in the
split, and whose payload holds the embedded `text` and the row's text
`fields`.

A collection keeps the commit it was built from. Once the dataset has a newer
commit, its page says so and **Rebuild** embeds the new version. The rebuild
fills a Qdrant collection of its own, and the collection's name is switched to
it once it is complete: search and the retrieval test keep answering on the
previous version meanwhile, and a rebuild that fails or is cancelled leaves
that version in place. Outside the app, the name is an alias in Qdrant.

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
the same rows. Once the split has more than one collection, the test tab lists
them side by side under **Collections of this split**, best first: model,
embedded columns, found first, in the top k, MRR and rows tested. A test run
with another question column, sample size or top k is flagged, since its
figures don't compare.
:::

::: warning Embed the answers, ask with the questions
When the question column is embedded too, every question finds its own text
and the test is meaningless; the page says so. Embed the answer (and its
context) alone to measure retrieval.
:::

## Use it from your own code

**Use it** gives the collection's Qdrant name and a Python snippet that queries
it with `qdrant-client`, embedding the query with the `openai` client on the
same endpoint and model id as the build.

::: warning An endpoint model is named by its id
A collection built with `openai:embed-default` is searched with whatever your
endpoint serves under `embed-default` at the time. If the alias moves to
another model, or you switch to another endpoint, rebuild the collection.
A build records the host of the endpoint that embedded it: when yours is no
longer that one, the collection's page says so and offers to build it again.
A model changed behind the same alias, on the same host, cannot be told.
:::

## Limits

- Qdrant must be configured: see [Configuration](./configuration.md). Without
  it the page says so and offers nothing to build.
- Deleting a collection, or an account, drops its vectors from Qdrant. If
  Qdrant is down at that moment, the worker drops them within the hour: it
  removes this deployment's collections (prefix, then `c_` and an id) that no
  row names any more.
- A collection built with one of the local models the server used to run
  (multilingual MiniLM, BGE, MiniLM L6) can no longer be searched or rebuilt:
  delete it and build it again with an endpoint model.
- 20 collections per user, and one build at a time.
- Builds count towards the job quotas (`QUOTA_ACTIVE_RUNS`,
  `QUOTA_RUNS_PER_DAY`, see [Jobs](./jobs.md)).
- Deleting a collection drops its vectors; deleting your account drops all of
  them, those of a build still running included. The data export lists your
  collections, without their vectors.
