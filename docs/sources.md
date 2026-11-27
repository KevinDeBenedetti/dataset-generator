---
title: Data sources
---

# Data sources

A **data source** is a configured origin of rows: a **connector** kind plus its
settings (see the [Glossary](https://github.com/KevinDeBenedetti/dataset-generator/blob/main/GLOSSARY.md)).
A recipe turns a data source's rows into a dataset. Every data source belongs to
one user: another user's answers 404.

| Route                                         | What it does                                                          |
| --------------------------------------------- | --------------------------------------------------------------------- |
| `GET /connectors`                             | The connector kinds, with their form (JSON Schema), in your language  |
| `GET /data-sources`, `POST /data-sources`     | Your data sources; a new one (not a file: see below)                  |
| `POST /data-sources/upload`                   | A new data source from a file you send                                |
| `POST /data-sources/{source_id}/test`         | A REST data source's first page: the records and columns found        |
| `PUT/DELETE /data-sources/{source_id}/secret` | The data source's own secret (a header value, an API key): write-only |
| `GET/PATCH/DELETE /data-sources/{source_id}`  | One data source; deleting it deletes its recipes and its file         |

## Upload

`POST /data-sources/upload` (multipart: `file`, `name`, and optionally
`licence`, `format`, `delimiter`, `encoding`, `sheet`, `json_path`) streams the
file into your storage (the [draft store](./storage.md#tabular-drafts)), at most
`UPLOAD_MAX_BYTES` (200 MB by default): a larger body is refused before it is
read. The file is then recognised:

- **Format** from its first bytes: Parquet (`PAR1`), Excel `.xlsx` (a ZIP with
  `xl/`), JSON (an array or an object), JSON Lines (one object per line), else
  delimited text (CSV or TSV). A file whose content contradicts its name, such
  as a CSV named `.json`, is refused; old `.xls` files are refused too.
- **Encoding** of text: UTF-8 (with or without a BOM), else Windows-1252, else
  Latin-1 — the encodings data.gouv.fr files use.
- **Delimiter** of text: `;`, `,`, tab or `|`, as the first lines show.
- An Excel workbook gives one sheet per data source: name it when there are several.

The form's values override what was detected. The **licence** is what you
state; it decides later whether a dataset may be public. The data source's
fingerprint is the file's SHA-256: uploading another file makes another data
source.

## SQL dumps

A file named `.sql` or `.sql.gz` sent to `POST /data-sources/upload` becomes a
`sql_dump` data source: a plain-SQL dump of PostgreSQL (`pg_dump`, `COPY … FROM
stdin` blocks included), MySQL (`mysqldump`) or SQLite (`.dump`), its dialect
detected. It is never run against the app's database: each run loads it into a
throwaway DuckDB confined to the run's folder (the engine's sandbox), within
`ENGINE_TIMEOUT_S`, and `UPLOAD_MAX_BYTES` is also the most it may weigh once
decompressed.

Only three kinds of statement are loaded, each parsed in the dump's dialect
and written back as DuckDB SQL:

- `CREATE TABLE`, reduced to its columns and their types (keys, indexes,
  defaults and constraints are left out);
- `INSERT … VALUES` of literal values (no function, no query);
- the rows of a `COPY … FROM stdin` block.

The housekeeping dump tools write around them (`SET`, `LOCK TABLES`,
`CREATE INDEX`, `ALTER TABLE … ADD CONSTRAINT`, `GRANT`, `DROP TABLE IF
EXISTS`…) is skipped without being run. Anything else refuses the whole dump
before any statement runs: `DROP DATABASE`, `COPY … TO` or `FROM PROGRAM`, a
function, an extension, `ATTACH`, `CREATE TABLE … AS SELECT`, a psql `\`
command. A `pg_dump` custom-format archive (`-Fc`) is refused too: export it as
plain SQL (`pg_dump -Fp`, or `pg_restore -f dump.sql`).

The upload lists the tables the dump creates, with their row counts
(`config.tables`); the data source's `config.table` names the one that is the
data, set at once when there is only one, else picked on the **Data sources**
page (or with `PATCH /data-sources/{source_id}`). The fingerprint is the dump's
SHA-256.

## data.gouv.fr

The `datagouv` connector searches the national open data catalogue
(`GET /connectors/datagouv/discover?q=…`, through the
[catalogue API](https://www.data.gouv.fr/api/1/datasets/)) and lists each
dataset with its organisation, licence and readable resources (CSV, CSV.GZ,
TSV, JSON, JSONL, Parquet, XLSX), saying which ones the
[tabular API](https://tabular-api.data.gouv.fr/api/) parsed;
`GET /connectors/datagouv/resources/{resource_id}/profile` shows that API's
profile (header, column formats, encoding, separator). A data source's config
is `{"dataset_id", "resource_id", "mode", "filters"}`:

- `file` (the default) downloads the resource's file. Only files hosted on
  data.gouv.fr are read (`www.data.gouv.fr`, `static.data.gouv.fr`): redirects
  are followed to those hosts only, each hop through the outbound guard; a
  resource hosted elsewhere is refused. The tabular API's encoding and
  separator are the default reading options.
- `tabular_api` pages through the tabular API's rows, 200 a page, at most 500
  pages, with server-side `filters` (`{"column", "op": "exact" | "differs" |
  "contains" | "in" | "less" | "greater", "value"}`): a subset of a large
  resource. The tabular API itself reads CSV and CSV.GZ files up to 100 MB,
  XLS up to 50 MB, XLSX up to 12.5 MB and Parquet up to 50 MB.

The provenance carries the organisation as producer, the dataset's page, its
licence (mapped as in [Datasets on Hugging Face](./datasets.md#tabular-datasets))
and the resource's last modification. The fingerprint is the resource's
checksum, else its modification date and size, else the file's SHA-256. A rate
limit (429) is retried after its `Retry-After` (30 s at most, three times); an
unreachable API or a refusal is reported in words, never as a stack trace.

## File at a URL

The `url` connector reads a direct link: `{"url", "format"?, "delimiter"?,
"encoding"?, "sheet"?, "json_path"?, "header_name"?, "producer"?}`.

- Only `https` URLs, without credentials in them. Every request goes through
  the outbound guard: the host is resolved and must have public addresses
  only, and the connection goes to the address checked (a DNS answer can't
  switch to a private one in between). A redirect is followed only to the same
  site (the same registrable domain, still https), at most five times; one to
  another site — or to a private or metadata address — is refused.
- The file is streamed under `UPLOAD_MAX_BYTES`, 60 s at most. Its format
  comes from `Content-Type`, then the extension, then its first bytes; a `.gz`
  is unzipped, a `.zip` holding one file is extracted, refused when it expands
  more than 100 times or past the limit (an Excel workbook is a ZIP too, and
  is read as one).
- `header_name` sends a header (`Authorization`, `X-API-Key`…) whose value is
  the data source's secret, saved with `PUT /data-sources/{source_id}/secret`,
  encrypted and never returned.
- The fingerprint is a strong `ETag`, else `Last-Modified` and
  `Content-Length`, else the file's SHA-256. A refresh asks with
  `If-None-Match` / `If-Modified-Since`: a `304` means the file has not changed.
- The licence and the producer are what you state, as for an upload.

## REST APIs

The `rest` connector reads the JSON pages of one GET endpoint:

| Field                      | What it says                                                                                                                                                                                                                                    |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `url`, `params`            | The https endpoint and its query parameters                                                                                                                                                                                                     |
| `auth`                     | `none`, `header` or `query` (`type`) and the header or parameter `name`: where the API key goes (the key is the secret)                                                                                                                         |
| `records_path`             | Where the records are: `$` (the whole answer), `$.results`, `$.data[0].items`                                                                                                                                                                   |
| `total_path`               | Optional: where the API says how many records there are (`$.total`)                                                                                                                                                                             |
| `pagination`               | `none`, `page` (`page_param`, `start_page`), `offset` (`offset_param`), `cursor` (`cursor_path`, `cursor_param`), `link_header` (the `Link: <…>; rel="next"` header) or `next_url` (`next_url_path`); `size_param` and `size` for the page size |
| `max_pages`, `max_records` | Where the fetch stops (200 pages, 1 000 000 records by default), with a warning shown in the review                                                                                                                                             |
| `rate_limit_per_s`         | Requests a second at most (5 by default)                                                                                                                                                                                                        |
| `producer`                 | Who publishes the data, for the card                                                                                                                                                                                                            |
| `preset`                   | The [ready-made preset](#french-public-apis) it came from: its rate limit and depth cap hold even when the config is edited                                                                                                                     |

Requests go through the outbound guard, like a [file at a URL](#file-at-a-url):
https only, public addresses, a redirect or a next page on the same site only;
a 429 or 503 is retried after its `Retry-After`, with backoff. The API key is
saved with `PUT /data-sources/{source_id}/secret`, sent as the header or the
query parameter `auth.name`, and never appears in a log, an error, the
provenance or the card. Records are flattened one level — `{"geo": {"lat":
48}}` becomes a `geo.lat` column — deeper objects and arrays are kept as JSON
text. The fingerprint is the first page's digest with the total, when
`total_path` gives one, else the SHA-256 of every record. Paging stops at
`max_records` without asking for one more page, and a `cursor` that comes back
unchanged is the last page.

A worked example, the communes of the Finistère from the
[Géo API](https://geo.api.gouv.fr/decoupage-administratif/communes) (no key,
one page):

```json
{
  "url": "https://geo.api.gouv.fr/departements/29/communes",
  "params": {"fields": "nom,code,codesPostaux,population", "format": "json"},
  "records_path": "$",
  "pagination": {"type": "none"},
  "producer": "Géo API (DINUM)"
}
```

## Remote PostgreSQL

A `sql_remote` data source reads one table of your own PostgreSQL database.
It is off until an admin lists the database hosts it may reach, under
**Platform** → `allowed_sql_hosts` (empty: every host is refused). Then:

- The host must be on that list and resolve to public addresses only; the
  connection goes to the address that was checked, the name kept for TLS.
- TLS is required, with the server's certificate verified against the
  system's roots (`sslmode=verify-full`).
- The session is read-only (`default_transaction_read_only`), with a
  `statement_timeout` (`statement_timeout_s`, 60 s by default, 300 at most).
- You name a `schema`, a `table` and optionally its `columns`; there is no SQL
  to write. Rows are streamed into Parquet up to `max_rows` (100 000 by
  default, 1 000 000 at most), with a warning when the table holds more.
- The password is the data source's secret
  (`PUT /data-sources/{source_id}/secret`), never in its config, a log or an
  error; **Test** reads the first 20 rows.

Give it an account that can only read that table: the read-only session is a
second line, not the first.

## French public APIs

The REST form offers ready-made presets (`GET /connectors/rest/presets`): pick
one, fill its few fields, and `POST /connectors/rest/presets/{preset_id}`
returns the `rest` config, name and licence that `POST /data-sources` then
adds. Their rate limit is below the API's own, since every user of the app
calls from the same address, and holds even when the config is edited.

| Preset                              | API                                                                                                                              | Key                                                                                                                  | Licence             | Limits kept                                                            |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------- | ---------------------------------------------------------------------- |
| `geo-communes`, `geo-divisions`     | [Géo API](https://geo.api.gouv.fr/decoupage-administratif) (DINUM, INSEE's COG)                                                  | none                                                                                                                 | Licence Ouverte     | 10 calls/s (the API allows 50/s per address); one answer, no paging    |
| `adresse-search`, `adresse-reverse` | [API Adresse](https://geoservices.ign.fr/documentation/services/services-geoplateforme/geocodage) (BAN on the IGN Géoplateforme) | none                                                                                                                 | Licence Ouverte 2.0 | 10 calls/s (50/s allowed); 50 results an answer, no paging             |
| `annuaire-offices`                  | [Annuaire de l'administration](https://api-lannuaire.service-public.gouv.fr/api/explore/v2.1/swagger.json) (DILA)                | none                                                                                                                 | Licence Ouverte     | 5 calls/s; 10 000 records (the portal refuses offset + limit above it) |
| `sirene-establishments`             | [Sirene](https://portail-api.insee.fr/catalog/api/2ba0e549-5587-3ef1-9082-99cd865de66f/doc) (INSEE)                              | an account and a key on [portail-api.insee.fr](https://portail-api.insee.fr/), sent as `X-INSEE-Api-Key-Integration` | Licence Ouverte 2.0 | 0.5 calls/s (30 a minute for open-data use); cursor paging             |

- **Géo API**: the communes of a département (or of France) with their codes,
  postcodes, population and surface; or the départements or the regions.
- **API Adresse**: geocoding of one text, or the addresses nearest a point. For
  many addresses, the CSV geocoding endpoint is a file POST no connector sends:
  use the BAN's own files instead, one CSV per département
  (`https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-29.csv.gz`),
  with [File at a URL](#file-at-a-url).
- **Annuaire de l'administration**: the public offices of a département —
  optionally of one kind (`mairie`, `prefecture`…) — with addresses, phones and
  opening hours. The `affectation_personne` field, which names the people in
  charge, is never asked for.
- **Sirene**: the establishments an INSEE multicriteria query finds (`q`, e.g.
  `codeCommuneEtablissement:29019`). A sole trader's legal unit is a person:
  their names, sex, birth date and place and nationality come with every
  establishment, so a new recipe of this data source starts with `mask` steps
  that drop those columns.
