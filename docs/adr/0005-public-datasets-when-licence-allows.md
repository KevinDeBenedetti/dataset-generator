---
title: "5. Datasets are private by default, public when the licence allows it"
---

# 5. Datasets are private by default, public when the licence allows it

## Context

Every Hub dataset repo the app writes was private: `services/hub_repo.py`
refuses a repo that is not (`RepoNotPrivate`). Open data comes with a licence
(Licence Ouverte / Etalab, ODbL, CC BY …) that usually allows, and sometimes
asks for, redistribution with attribution.

Alternatives considered: keeping every dataset private; letting the user make
any dataset public.

## Decision

- A dataset stays private by default.
- It may be public only when its data source's licence is known and allows
  redistribution. The rule relaxes `RepoNotPrivate` for those datasets only.
- The app card carries the licence, the producer and the attribution, and the
  repo holds a provenance manifest.

## Consequences

- Datasets from personal data (GitHub, resume, files) can never become public
  through the app.
- The licence becomes part of a data source's provenance, and an unknown
  licence means private.
- Publication tests must cover both the private default and the public case.

Governs: [#309](https://github.com/KevinDeBenedetti/dataset-generator/issues/309), [#311](https://github.com/KevinDeBenedetti/dataset-generator/issues/311).
