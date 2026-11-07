---
title: Jobs
---

# Jobs

The API **queues** dataset jobs; a worker (`python -m server.worker`, the `worker`
service) executes them, with the owner's own keys. Any number of workers can run
(`FOR UPDATE SKIP LOCKED`). A run whose worker dies becomes **interrupted** after
two minutes and is never re-run on its own. SIGTERM drains for
`WORKER_DRAIN_SECONDS`. Per-user quotas: `QUOTA_ACTIVE_RUNS`, `QUOTA_RUNS_PER_DAY`,
`QUOTA_DATASETS` (`0` = unlimited).

The scheduled GitHub Actions jobs run the same code on the server's own keys
(`OPENAI_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `HF_TOKEN`, `GITHUB_TOKEN`,
`HF_QA_DATASET_REPO`… as repository secrets and variables).

A recipe's run — the GitHub-fed datasets — is a job too; see
[GitHub recipes](./github.md). So is the build of a
[vector collection](./collections.md), one at a time per user. How the worker is deployed is in
[Production](./production.md).
