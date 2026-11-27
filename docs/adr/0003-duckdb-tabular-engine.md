---
title: "3. DuckDB is the tabular engine; recipe steps are JSON compiled to SQL"
---

# 3. DuckDB is the tabular engine; recipe steps are JSON compiled to SQL

## Context

Tabular data sources must be read (CSV, TSV, JSON, JSONL, Parquet, XLSX),
typed, profiled, transformed and written as Parquet, on files larger than
memory, inside the API and worker processes.

Alternatives considered: pandas or polars data frames in Python; the
Hugging Face `datasets` library.

## Decision

- DuckDB reads, profiles, transforms and writes Parquet, in a sandboxed
  connection (no extension install, no access outside the run's files).
- A recipe's steps (select, rename, cast, filter, dedup, mask, limit) are JSON
  objects the server validates and compiles to SQL. Users never write SQL.

## Consequences

- Out-of-core processing and Parquet output with one dependency and no data
  frame in memory.
- The step vocabulary is closed: a new transformation means a new step kind,
  its validation and its SQL, with tests.
- Compiling steps is the one place where identifiers and literals are quoted,
  which keeps SQL injection in one reviewed module.

Governs: [#305](https://github.com/KevinDeBenedetti/dataset-generator/issues/305), [#306](https://github.com/KevinDeBenedetti/dataset-generator/issues/306), [#319](https://github.com/KevinDeBenedetti/dataset-generator/issues/319), [#322](https://github.com/KevinDeBenedetti/dataset-generator/issues/322).
