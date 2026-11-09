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

Every run starts from the app; nothing runs on a schedule. The **GitHub** page
starts the two jobs built from your whole account, **GitHub personal Q&A** and
the **knowledge corpus**, and a recipe's run; see
[GitHub datasets](./github.md). The build of a
[vector collection](./collections.md) is a job too, one at a time per user.
How the worker is deployed is in [Production](./production.md).
