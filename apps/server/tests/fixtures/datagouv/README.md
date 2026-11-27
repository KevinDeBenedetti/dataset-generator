# data.gouv.fr answers

Recorded on 2026-11-27 from the public APIs, for *Population des communes du
Finistère* (Conseil départemental du Finistère, Licence Ouverte v2.0), then
trimmed to the fields the connector reads:

- `search.json`: `GET https://www.data.gouv.fr/api/1/datasets/?q=…&page_size=2`
- `dataset.json`: `GET https://www.data.gouv.fr/api/1/datasets/62b25c51ea3141106f538362/`
  (three of its resources: CSV, XLSX, Parquet)
- `profile.json`: `GET https://tabular-api.data.gouv.fr/api/resources/984916d0-18e3-439e-a795-352f10389e4f/profile/`
- `data-page-1.json`: `…/data/?page=1&page_size=3`; `data-page-2.json` is
  made from it (two rows, no next link) to stand for a last page.
