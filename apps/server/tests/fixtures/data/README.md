# Test data

The rows come from the first 20 communes of *Population des communes du
Finistère*, published on data.gouv.fr by the Conseil départemental du Finistère
under the Licence Ouverte v2.0
(<https://www.data.gouv.fr/datasets/population-des-communes-du-finistere>).

- `communes-finistere-utf8bom.csv`: the excerpt as published (UTF-8 with a BOM,
  `;`, CRLF).
- `communes-finistere-cp1252.csv`: the same rows in Windows-1252, the other
  encoding data.gouv.fr files commonly use.
- `communes.tsv`, `.json`, `.jsonl`, `.parquet`, `.xlsx`: the same rows in each
  format the upload connector reads (the XLSX holds the first five).
