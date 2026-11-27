---
title: "1. The app is an open-data workshop for the Hub"
---

# 1. The app is an open-data workshop for the Hub

## Context

The app turned the owner's own GitHub account, resume, PDFs and web pages into
private Q&A datasets. Most useful data people want on the Hugging Face Hub is
already structured and public: CSV, JSON, Parquet and XLSX files, French open
data on data.gouv.fr, REST and government APIs, SQL dumps. Turning such data
into a clean, documented and reviewed Hub dataset repo is the gap.

The real alternatives were to keep the app a personal Q&A generator, or to add
tabular sources beside it as a second product.

## Decision

The app becomes a workshop that takes a **data source**, runs a **recipe** on
it, produces a draft a human reviews, and publishes it as a Hub dataset repo
that stays up to date. One recipe describes the whole path; every run produces
a draft; only a human approval publishes.

Kept: drafts and review, quality rules, the near-duplicate check, safe
publication through `services/hub_repo.py` (`parent_commit`, moved dataset
detection, app card), the job queue and worker, schedules, vector collections,
per-user encrypted secrets, the `core/net.py` outbound guard, i18n. GitHub,
resume, file and web page generation become connectors among others.

Retired: Infomaniak/GitHub SSO, password accounts for users, email
verification and `ADMIN_EMAILS` (see [ADR 2](./0002-sign-in-hf-token-and-admin-secrets.md)).

## Consequences

- One pipeline (data source → connector → engine → generator → draft →
  review → publication) instead of one code path per input kind.
- A table with no model call becomes the first output; Q&A and corpus come
  from rows afterwards.
- The existing jobs and pages are ported, then retired, which is a long
  migration ([#318](https://github.com/KevinDeBenedetti/dataset-generator/issues/318)).

Governs: [#296](https://github.com/KevinDeBenedetti/dataset-generator/issues/296) and every child issue of that map.
