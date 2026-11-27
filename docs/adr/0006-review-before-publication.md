---
title: "6. Nothing reaches the Hub without a review"
---

# 6. Nothing reaches the Hub without a review

## Context

Data sources change, and a refresh can bring bad rows, personal data or a
broken schema. The app already reviews Q&A drafts row by row before
publication. A table of thousands of rows cannot be reviewed that way.

Alternatives considered: publishing every run automatically; reviewing tables
row by row.

## Decision

- A tabular draft is reviewed as a whole: schema, profile, quality report and
  a paged sample, then approved or rejected.
- Q&A drafts stay reviewed row by row.
- Nothing is published without an approval, with one exception: a scheduled
  refresh of a recipe that was approved with "publish what passes" publishes
  the rows that pass its rules.

## Consequences

- The review page and the quality report are on the critical path of every
  publication.
- Scheduled refreshes stay hands-off only for recipes their owner chose to
  trust; the others wait as drafts.

Governs: [#307](https://github.com/KevinDeBenedetti/dataset-generator/issues/307), [#308](https://github.com/KevinDeBenedetti/dataset-generator/issues/308), [#314](https://github.com/KevinDeBenedetti/dataset-generator/issues/314), [#316](https://github.com/KevinDeBenedetti/dataset-generator/issues/316).
