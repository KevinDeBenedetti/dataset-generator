// Pure state of a resume's dataset form (resume-dataset.tsx): what it shows
// from the saved settings, and what it sends back (PUT /resumes/{id}/dataset).
// Relative imports only: vitest has no `@/` alias.
import type { ResumeDatasetIn, ResumeDatasetOut, ResumeOut } from '../../api/types'
import { defaultTargetRepo } from '../github/recipe-state'

export type Every = '' | 'day' | 'week' | 'month'

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
  const [hour = 3, minute = 0] = form.time.split(':').map((n) => Number(n) || 0)
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
