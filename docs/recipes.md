---
title: Recipes
---

# Recipes

A **recipe** says what to do with one [data source](./sources.md): its
**steps**, its output kind (a table for now), the Hub dataset repo it publishes
to and its visibility. Steps are JSON, checked by the server and compiled to
one DuckDB query in the run's sandbox
([ADR 3](./adr/0003-duckdb-tabular-engine.md)): nobody writes SQL. Each step
reads the table the previous one made; a step that names a column the table
no longer has is refused, with its number.

| Route                                   | What it does                                                                                                                 |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `GET /recipes`, `POST /recipes`         | Your recipes; a new one                                                                                                      |
| `GET/PATCH/DELETE /recipes/{recipe_id}` | One recipe; deleting it deletes its runs' files                                                                              |
| `POST /recipes/{recipe_id}/preview`     | The first 100 rows after the steps (`{"steps": [...]}` tries unsaved ones), the rows after each step, the first failing step |
| `POST /recipes/{recipe_id}/run`         | Queues a run (`job_id` `recipe`): follow it with `GET /jobs/runs/{run_id}`                                                   |

A preview runs on the data source's loaded table, kept in your storage until
its settings change, with a 20-second limit; 30 previews a minute. A run
fetches the data source, applies the steps and writes the draft: its rows as
Parquet in your storage, and in the run its schema, column profile, row count
after each step, provenance and fingerprint.

## Steps

### `select`

Keep these columns, in this order.

```json
{"op": "select", "columns": ["code", "libelle", "population"]}
```

### `rename`

```json
{"op": "rename", "mapping": {"libelle": "commune"}}
```

### `cast`

Change a column's type: `integer`, `double`, `date`, `timestamp`, `boolean` or
`text`. `format` reads dates written another way (`strptime` codes);
`decimal_comma` reads numbers written `1 284,5`. A value that doesn't convert
becomes empty (`"on_error": "null"`, the default) or stops the run (`"fail"`).

```json
{"op": "cast", "column": "date_maj", "to": "date", "format": "%d/%m/%Y"}
{"op": "cast", "column": "surface", "to": "double", "decimal_comma": true}
```

### `filter`

Keep the rows where the column is `eq`, `ne`, `lt`, `le`, `gt`, `ge` the value,
`in` / `not_in` a list, `contains` some text, `is_null` or `not_null`.

```json
{"op": "filter", "column": "population", "operator": "ge", "value": 2000}
{"op": "filter", "column": "departement", "operator": "in", "value": ["29", "56"]}
```

### `dedup`

Keep one row per value of these columns (every column when none is given),
the `first` or the `last` in the file's order.

```json
{"op": "dedup", "columns": ["siret"], "keep": "last"}
```

### `mask`

Hide a column's values: `drop` the column, `hash` them (SHA-256), `redact`
them (`***`), or `truncate` them to `keep` characters.

```json
{"op": "mask", "column": "email", "method": "hash"}
{"op": "mask", "column": "nom", "method": "truncate", "keep": 1}
```

### `trim`

Remove the spaces around the values of these text columns (every text column
when none is given).

```json
{"op": "trim", "columns": ["libelle"]}
```

### `limit`

Keep the first rows.

```json
{"op": "limit", "rows": 1000}
```

## Quality report

Every run's draft carries a quality report, computed after the steps and shown
in the review:

- **Personal data**: per text column, the share of matching values on a random
  sample of at most 10 000 rows — e-mail addresses, French phone numbers, IBANs
  (with their check digits), NIR (with their key) and IP addresses — and column
  names that say so (`nom`, `prenom`, `email`, `telephone`, `adresse`,
  `date_naissance`…). Each candidate comes with a `mask` step to add; a column
  a `mask` step already covers counts as masked.
- **Structure**: empty columns, constant columns, columns more than half empty,
  duplicated rows, and the row count against the recipe's last published
  version.
- **Rules**, the `tabular` section of your quality rules (`PUT /quality-rules`):
  `min_rows`, `max_null_share`, `required_columns` (failing as `severity`:
  `warn` by default, or `block`), and `unmasked_pii`: `auto` (the default)
  blocks unmasked e-mails, phone numbers and NIR in a public dataset and warns
  otherwise; `block`, `warn` or `off` apply to every candidate. A blocking rule
  stops the approval.

## Scheduled refresh

A recipe can refresh by itself every day, week or month at a time of day (UTC),
from its page. At each due time the worker checks the data source first, as
cheaply as its connector allows: a data.gouv.fr resource's checksum (one
catalogue call), a URL's `ETag` or `Last-Modified` (a conditional `HEAD`: a 304
means unchanged), an uploaded file (it never changes). When the data source has
the fingerprint of the last run and the recipe was not edited since, no run
starts and the schedule says "unchanged since <date>". A data source without a
cheap check (a REST API) is fetched, and a run that finds the same fingerprint
ends with nothing to review.

A run that finds new data makes a draft. With **Publish what passes the rules**
on, it publishes it at once when no blocking rule of the quality report fails
(and the licence allows the visibility), with the commit message
`refresh: <producer> <date>`, a new retrieval date on the card, and the previous
fingerprint in the manifest; otherwise the draft waits for your review, listed
on the dashboard. Runs count against `QUOTA_RUNS_PER_DAY`, and one recipe run
goes at a time: a schedule due while another recipe runs is tried again a few
minutes later.

## Q&A from templates

A recipe whose output is `qa` with `"generator": "facts"` turns every row of
its table into question/answer pairs, with no model: **facts**, rebuilt on
every run.

```json
{
  "generator": "facts",
  "key_column": "code",
  "templates": [
    {"question": "Quelle est la population de {nom} ?", "answer": "{nom} compte {population|number} habitants."},
    {"question": "Quelle est la superficie de {nom} ?", "answer": "{surface|decimal} km²", "condition": {"column": "surface", "operator": "not_null"}}
  ],
  "max_pairs": 10000
}
```

A placeholder is `{column}` or `{column|filter}` — `number` (French grouping,
`139 926`), `decimal` (`49,51`), `date_fr` (`2 janvier 2026`), `lower`,
`upper`, `title`; `{{` and `}}` print braces. Nothing else is interpreted: no
expression, attribute or call, so a template only ever prints values; a
template is 1 000 characters at most, a rendered field 4 000. A `condition`
(the `filter` step's operators) applies a template to some rows only;
`max_pairs` bounds a run. With a `key_column`, a pair's id follows its row and
template, so a changed value replaces the published pair; without one, the id is
the pair's content. The preview shows the pairs of the first 20 rows.

The run's draft is reviewed pair by pair and published like a file draft
(`/drafts/runs/{run_id}`): the pairs join the dataset's `data/train.jsonl`,
read by the **Datasets** pages.

## Q&A with your model

With `"generator": "llm"`, the rows become text **sources** your model turns
into question/answer pairs, through the same incremental build as the GitHub
and resume datasets:

```json
{
  "generator": "llm",
  "subject": "les communes du Finistère",
  "group_size": 20,
  "pairs_per_group": 5,
  "row_template": "{nom} ({code}) : {population|number} habitants",
  "language": "fr"
}
```

A row reads as its `row_template` (the syntax of the templates above) or as
`column: value` lines; rows form a source by `group_by` (one source per value
of a column) or by `group_size`, 6 000 characters at most, `max_groups`
sources at most. A source's content hash drives the incrementality: an
unchanged source keeps its pairs with no model call, a changed one is
re-checked and regenerated; the grader holds a pair graded below 0.6 for
review with its reason, and new pairs are screened for near-duplicates.

The model is the one of the recipe (`model_ref`), else your default LLM, on
your OpenAI-compatible key from **Settings**; the preview says when it is
missing. Before calling it, the run estimates the tokens a full run would
spend and refuses above `QUOTA_TOKENS_PER_RUN` (2 000 000 by default); the
preview shows the estimate. The draft is reviewed pair by pair and published
to the repo's `train.jsonl` with its review list and manifest, like a GitHub
Q&A dataset.

## Corpus documents

With `"output_kind": "corpus"`, each row becomes a retrieval document
`{id, title, text, metadata}` instead of a row of the table:

```json
{
  "text_template": "{nom} : {description}",
  "title_template": "{nom}",
  "metadata_columns": ["departement", "type"],
  "id_column": "code",
  "chunk_chars": 1200
}
```

`text_template` and `title_template` use the syntax of the templates above.
`id_column` names each document (else the row's position); `chunk_chars`
(200 to 20 000) cuts a longer text at paragraph, then sentence, then word
boundaries, the chunks numbered `<id>-1`, `<id>-2`… `metadata_columns` stay
typed fields of a `metadata` struct. The draft is reviewed and published as a
table (Parquet, an app card tagged `corpus`), and its review page links to
**Create a collection** with the text column and the title as the retrieval
test's query, so the collection can be built, searched and filtered on the
metadata ([Vector collections](collections.md#search-it)).
