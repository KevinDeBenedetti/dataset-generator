---
title: "4. Tabular draft rows live as Parquet on storage, not in Postgres"
---

# 4. Tabular draft rows live as Parquet on storage, not in Postgres

## Context

A tabular draft can hold millions of rows with any columns. Postgres holds the
app's state (users, recipes, runs, reviews); its tables have fixed columns,
and the local dataset tables are being retired ([#277](https://github.com/KevinDeBenedetti/dataset-generator/issues/277)).

Alternatives considered: rows as JSON in Postgres; rows written to the Hub on
a draft branch.

## Decision

- A **tabular draft**'s rows are a Parquet file on the storage volume;
  Postgres keeps only its metadata (schema, profile, quality report, path,
  checksum, review state).
- Q&A pairs keep their current storage.
- The new draft model does not depend on `datasets`, `qa_pairs` or
  `dataset_runs`.

## Consequences

- The file reviewed is the file published: no conversion between review and
  publication.
- Storage needs a lifecycle: a rejected or published draft's file is removed,
  and production needs a volume (or a bucket) sized for drafts
  ([#303](https://github.com/KevinDeBenedetti/dataset-generator/issues/303)).
- Backups of Postgres alone no longer hold pending drafts.

Governs: [#303](https://github.com/KevinDeBenedetti/dataset-generator/issues/303), [#305](https://github.com/KevinDeBenedetti/dataset-generator/issues/305), [#308](https://github.com/KevinDeBenedetti/dataset-generator/issues/308), [#309](https://github.com/KevinDeBenedetti/dataset-generator/issues/309).
