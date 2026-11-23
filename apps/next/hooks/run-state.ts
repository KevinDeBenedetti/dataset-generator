// A job run's lifecycle as the web app watches it (apps/server/services/queue.py).

/** The statuses a run is polled in: it may still change. */
export const ACTIVE_RUN = new Set(['queued', 'running', 'publishing'])

/** Whether a run seen active before has just finished: the moment what it
 *  made (a draft, a published dataset) can be shown. */
export function runEnded(previous: string | undefined, next: string): boolean {
  return previous !== undefined && ACTIVE_RUN.has(previous) && !ACTIVE_RUN.has(next)
}
