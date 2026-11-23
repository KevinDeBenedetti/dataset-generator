---
title: Jobs
---

# Jobs

The API **queues** dataset jobs; a worker (`python -m server.worker`, the `worker`
service) executes them, with the owner's own keys. Any number of workers can run
(`FOR UPDATE SKIP LOCKED`), and a worker only claims the runs of jobs it knows: one
older than a job (an old pod during a rolling deploy) leaves its runs queued for
a newer one. In the local stack the worker restarts on every source change, like
the API. A run whose worker dies becomes **interrupted** after two minutes and is
never re-run on its own. A worker runs `WORKER_CONCURRENCY` runs at once
(default `1`). SIGTERM drains for `WORKER_DRAIN_SECONDS`. Per-user quotas: `QUOTA_ACTIVE_RUNS`, `QUOTA_RUNS_PER_DAY`,
`QUOTA_DATASETS` (`0` = unlimited). A file or web page draft is made in its
request, without the worker: it does not count towards `QUOTA_RUNS_PER_DAY`.

Runs start from the app, or on a schedule set in it: a
[resume's dataset](./resume.md#your-resume-as-a-dataset), a
[GitHub recipe's](./github.md#recipes) and the two whole-account GitHub jobs
can be regenerated every day, every
Monday or the 1st of every month at a time of day (UTC). The worker queues the
due runs with its sweep of stale ones (`job_schedules`, one row per user, job
and resume or recipe): with the owner's own keys, under the same
quotas, never two runs of a job at once, and once after a worker was down
rather than once per missed time. A schedule whose job already has a run in
progress (two recipes at the same time, say) is tried again every five
minutes until that run is done; one that can't be queued for another reason
(a model the endpoint no longer serves, a quota reached, an owner no longer
admin) waits for its next time, and its page says why under the schedule until
a run starts or the schedule is saved again. The **GitHub** page
starts the two jobs built from your whole account, **GitHub personal Q&A** and
the **knowledge corpus**, and a recipe's run; see
[GitHub datasets](./github.md). The build of a
[vector collection](./collections.md) is a job too, one at a time per user.
How the worker is deployed is in [Production](./production.md).
