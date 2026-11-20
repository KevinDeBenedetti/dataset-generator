// Pure state of a resume's dataset form (resume-dataset.tsx): what it shows
// from the saved settings, and what it sends back (PUT /resumes/{id}/dataset).
// Relative imports only: vitest has no `@/` alias.
import type { ResumeDatasetIn, ResumeDatasetOut, ResumeOut } from '../../api/types'
import { defaultTargetRepo } from '../github/recipe-state'
import { type Every, timeOf } from '../jobs/schedule-state'

export type { Every } from '../jobs/schedule-state'

export interface DatasetForm {
  target_repo: string
  language: ResumeDatasetIn['language']
  model_ref: string | null
  every: Every
  /** "HH:MM", UTC. */
  time: string
  publish: boolean
}

const pad = (n: number) => String(n).padStart(2, '0')

/** The saved settings, else the defaults for this resume: a dataset named
 * after it in your namespace, its own language, your LLM, no schedule. */
export function initialForm(
  resume: Pick<ResumeOut, 'name' | 'slug'>,
  saved: ResumeDatasetOut | null,
  namespace?: string | null,
): DatasetForm {
  return {
    target_repo:
      saved?.target_repo ?? defaultTargetRepo(`resume-${resume.slug || resume.name}`, namespace),
    language: saved?.language ?? 'auto',
    model_ref: saved?.model_ref ?? null,
    every: (saved?.every ?? '') as Every,
    time: `${pad(saved?.at_hour ?? 3)}:${pad(saved?.at_minute ?? 0)}`,
    publish: saved?.publish ?? true,
  }
}

/** The body the form saves. */
export function toSettings(form: DatasetForm): ResumeDatasetIn {
  const { at_hour: hour, at_minute: minute } = timeOf(form.time)
  return {
    target_repo: form.target_repo.trim(),
    language: form.language,
    model_ref: form.model_ref || null,
    every: form.every || null,
    at_hour: hour,
    at_minute: minute,
    publish: form.publish,
  }
}

/** A value of a run's result metrics — (label, value) pairs, in display
 * order — else null (an older run, or a label it doesn't have). */
export function runMetric(metrics: unknown, label: string): string | number | null {
  if (!Array.isArray(metrics)) return null
  for (const entry of metrics) {
    if (Array.isArray(entry) && entry[0] === label) {
      const value: unknown = entry[1]
      return typeof value === 'string' || typeof value === 'number' ? value : null
    }
  }
  return null
}

/** A metric found by its English label, shown in the reader's language: the
 * value at the same place in `metrics_display` (the server translates it),
 * else the stored one, else null. */
export function shownMetric(
  result: { metrics?: unknown; metrics_display?: unknown } | null | undefined,
  label: string,
): string | number | null {
  const metrics = result?.metrics
  if (!Array.isArray(metrics)) return null
  const index = metrics.findIndex((entry) => Array.isArray(entry) && entry[0] === label)
  if (index < 0) return null
  const shown: unknown = Array.isArray(result?.metrics_display)
    ? result.metrics_display[index]
    : undefined
  if (Array.isArray(shown)) {
    const value: unknown = shown[1]
    if (typeof value === 'string' || typeof value === 'number') return value
  }
  return runMetric(metrics, label)
}

/** Whether the form differs from what is saved (always, before a first save). */
export function isDirty(
  form: DatasetForm,
  resume: Pick<ResumeOut, 'name' | 'slug'>,
  saved: ResumeDatasetOut | null,
  namespace?: string | null,
): boolean {
  if (!saved) return true
  return (
    JSON.stringify(toSettings(form)) !==
    JSON.stringify(toSettings(initialForm(resume, saved, namespace)))
  )
}
