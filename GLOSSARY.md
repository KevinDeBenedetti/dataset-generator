# dataset-generator

Builds question/answer datasets from GitHub profiles, resumes, files and web pages, and keeps them as private dataset repos on the Hugging Face Hub.

## Language

### Datasets on the Hub

**Hub dataset repo**:
A dataset repository on the Hugging Face Hub that holds one dataset the app publishes: a Q&A dataset (its pairs, the job's review list and manifest when a job made it) or a table built from a data source (its Parquet files and manifest), and its card. Private, unless a table's licence allows it to be public.
_Avoid_: Hub dataset (alone), export, remote dataset

**Dataset version**:
The content of a Hub dataset repo at one commit; every read returns one and every publication creates the next.
_Avoid_: snapshot, revision, state

**Moved dataset**:
A Hub dataset repo whose latest commit is no longer the one a draft was built from, because something was published or edited in between.
_Avoid_: conflict, stale repo

**App card**:
A dataset card the app wrote, and may therefore replace on the next publication; any other card belongs to the dataset's owner and is left as it is.
_Avoid_: generated card, README

### Building a Q&A dataset

**Incremental Q&A build**:
The making of a dataset's next version from the published one: pairs of unchanged sources are kept, pairs of changed sources are re-checked and regenerated, and new pairs are screened before they join.
_Avoid_: pipeline, generation run, sync

**Source**:
One piece of text a Q&A job generates pairs from and tracks for changes, such as a repository's overview, one documentation file or one resume item.
_Avoid_: input, document, chunk

**Fact**:
A pair built directly from structured data, with no model call, and rebuilt on every run.
_Avoid_: deterministic pair, profile pair

### Rows

**Own row**:
A row of a dataset that the Q&A job publishing it generated.
_Avoid_: job pair, managed row

**Foreign row**:
A row of a dataset that the Q&A job publishing it did not generate, such as a pair added from a file; the job carries it through unchanged.
_Avoid_: external pair, unknown row

### Building a dataset from data

**Data source**:
A configured origin of rows: a connector kind plus its settings and the reference to its secret, such as one data.gouv.fr resource, one uploaded CSV or one REST endpoint. A **Source** is something else: the text unit a Q&A job tracks.
_Avoid_: source (alone), input, feed

**Connector**:
The code that fetches a data source's rows and reports their provenance.
_Avoid_: adapter, importer, plugin

**Recipe**:
What to do with a data source: its steps, its output kind (table, Q&A or corpus), its target Hub dataset repo and its schedule. Today's GitHub recipe becomes a recipe whose data source is GitHub.
_Avoid_: pipeline, job, config

**Step**:
One transformation in a recipe, such as select, rename, cast, filter, dedup or mask.
_Avoid_: operation, transform, rule (a quality rule checks rows, it does not change them)

**Provenance**:
Where and when a data source's rows came from: URL, resource id, fetch time, checksum, licence and producer.
_Avoid_: metadata, origin, lineage

**Fingerprint**:
The value that tells whether a data source changed since a recipe's last run.
_Avoid_: hash (alone), version, etag

**Tabular draft**:
A draft whose rows are a Parquet file, reviewed as a whole before publication.
_Avoid_: table draft, staged dataset
