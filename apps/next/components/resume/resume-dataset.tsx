'use client'

import Link from 'next/link'
import { type FormEvent, useState } from 'react'
import { toast } from 'sonner'
import '../jobs/jobs.css'
import type { JobRunOut, ResumeDatasetIn, ResumeDatasetOut, ResumeOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { ModelSelect } from '@/components/app/model-select'
import { HF_REPO_PATTERN } from '@/components/github/recipe-state'
import { datasetHref } from '@/components/hub/format'
import {
  useCancelJobRun,
  useDeleteResumeDataset,
  useHubDatasets,
  useJobRun,
  useResumeDataset,
  useRunResumeDataset,
  useSaveResumeDataset,
} from '@/hooks'
import { type DatasetForm, type Every, initialForm, isDirty, toSettings } from './dataset-state'

const EVERY: { value: Every; label: string }[] = [
  { value: '', label: 'Only when I generate it' },
  { value: 'day', label: 'Every day' },
  { value: 'week', label: 'Every Monday' },
  { value: 'month', label: 'The 1st of every month' },
]

const LANGUAGES: { value: ResumeDatasetIn['language']; label: string }[] = [
  { value: 'auto', label: 'The resume’s own' },
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'French' },
]

const ACTIVE = new Set(['queued', 'running', 'publishing'])

/** The sections a run couldn't generate, and why (the model's error). */
function RunErrors({ run }: { run: JobRunOut }) {
  const errors = run.result?.errors ?? []
  if (errors.length === 0) return null
  return (
    <details className="job-errors" open>
      <summary className="hint job-error">
        {errors.length} section(s) not generated — they are tried again next run
      </summary>
      <ul className="job-error-list">
        {errors.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </details>
  )
}

function LatestRun({ run, target }: { run: JobRunOut; target: string }) {
  const cancel = useCancelJobRun(run.id)
  if (run.status === 'queued' || run.status === 'running') {
    const { done = 0, total = 0, label = '' } = run.progress ?? {}
    const pct = total > 0 ? Math.round((done / total) * 100) : 4
    return (
      <div className="gh-run">
        <div className="hint">
          {run.status === 'queued'
            ? 'Queued — waiting for a worker.'
            : total > 0
              ? `Generating… ${done}/${total} sections${label ? ` · ${label}` : ''}`
              : label || 'Reading the resume…'}
        </div>
        <div className="job-progress">
          <div style={{ width: `${pct}%` }} />
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => cancel.mutate()}
          disabled={cancel.isPending || !!run.cancel_requested}
        >
          {run.cancel_requested ? 'Cancelling…' : 'Cancel'}
        </button>
      </div>
    )
  }
  if (run.status === 'publishing') {
    return <div className="gh-run hint">Publishing to Hugging Face…</div>
  }
  const metrics = (run.result?.metrics ?? []) as [string, unknown][]
  const unchanged = metrics[0]?.[0] === 'Unchanged'
  const when = run.finished_at ? new Date(run.finished_at).toLocaleString() : ''
  const datasetLink = <Link href={datasetHref(target)}>Open the dataset</Link>
  if (run.status === 'succeeded' && run.preview) {
    const preview = run.preview
    return (
      <div className="gh-run">
        {run.result?.url && (
          <div className="hint">
            Published {when} · {datasetLink}
          </div>
        )}
        <div className="gh-run-counts">
          <span>
            <b>{preview.new.length}</b> new
          </span>
          <span>
            <b>{preview.kept}</b> kept
          </span>
          {preview.review.length > 0 && (
            <span>
              <b>{preview.review.length}</b> held out
            </span>
          )}
          {(preview.removed ?? []).length > 0 && (
            <span>
              <b>{preview.removed?.length}</b> removed
            </span>
          )}
        </div>
        <div className="gh-run-review">
          <span className="hint">
            {run.result?.url
              ? 'Some pairs were held out: review them to publish them too.'
              : 'Draft ready: review it before it goes to Hugging Face.'}
          </span>
          <Link className="btn btn-primary btn-sm" href={`/drafts/runs/${run.id}`}>
            <Icon name="eye" />
            Review
          </Link>
        </div>
        <RunErrors run={run} />
      </div>
    )
  }
  if (run.status === 'published' || (run.status === 'succeeded' && run.result?.url)) {
    return (
      <div className="gh-run">
        <div className="hint">
          Published {run.published_at ? new Date(run.published_at).toLocaleString() : when} ·{' '}
          {datasetLink}
        </div>
        <RunErrors run={run} />
      </div>
    )
  }
  if (run.status === 'succeeded' && unchanged) {
    return (
      <div className="gh-run hint">
        {when}: nothing changed since the published version — no model call.
      </div>
    )
  }
  return (
    <div className="gh-run hint job-error">
      {run.status === 'cancelled'
        ? 'The last generation was cancelled.'
        : run.status === 'interrupted'
          ? 'The last generation was interrupted (its worker stopped). Generate again.'
          : `The last generation failed: ${run.error ?? 'unknown error'}`}
    </div>
  )
}

function DatasetCard({
  resume,
  saved,
  namespace,
}: {
  resume: ResumeOut
  saved: ResumeDatasetOut | null
  namespace?: string | null
}) {
  const [form, setForm] = useState<DatasetForm>(() => initialForm(resume, saved, namespace))
  const [fullRefresh, setFullRefresh] = useState(false)
  const save = useSaveResumeDataset(resume.id)
  const forget = useDeleteResumeDataset(resume.id)
  const start = useRunResumeDataset(resume.id)
  const run = useJobRun(saved?.latest_run?.id)
  const active = ACTIVE.has(run.data?.status ?? '')

  const settings = toSettings(form)
  const targetValid = HF_REPO_PATTERN.test(settings.target_repo)
  const dirty = isDirty(form, resume, saved, namespace)
  const set = (change: Partial<DatasetForm>) => setForm((f) => ({ ...f, ...change }))

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!targetValid) return
    save.mutate(settings, {
      onSuccess: () => toast.success('Dataset settings saved'),
      onError: (error) => toast.error(error.message),
    })
  }

  const generate = () =>
    start.mutate(fullRefresh, {
      onSuccess: () => toast.success('Generation queued: it stops at a draft to review'),
      onError: (error) => toast.error(error.message),
    })

  return (
    <form className="card rs-dataset" onSubmit={submit}>
      <div className="card-head">
        <div>
          <div className="card-title">Hugging Face dataset</div>
          <p className="card-desc">
            Q&amp;A pairs about you from this resume: exact facts from its fields (never the phone
            number) and pairs generated per section, deduplicated and checked against the text.
            Published to a private dataset.
          </p>
        </div>
      </div>

      <div className="card-body rs-dataset-grid">
        <div className="field">
          <label className="label" htmlFor="rs-target">
            Publishes to
          </label>
          <input
            id="rs-target"
            className="input mono"
            value={form.target_repo}
            aria-invalid={!targetValid}
            onChange={(e) => set({ target_repo: e.target.value })}
          />
          {!targetValid && <div className="hint job-error">A dataset id: namespace/name</div>}
        </div>
        <div className="field">
          <label className="label" htmlFor="rs-language">
            Language
          </label>
          <select
            id="rs-language"
            className="select"
            value={form.language}
            onChange={(e) => set({ language: e.target.value as DatasetForm['language'] })}
          >
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="label" htmlFor="rs-model">
            Model
          </label>
          <ModelSelect
            id="rs-model"
            className="select"
            value={form.model_ref ?? ''}
            onChange={(ref) => set({ model_ref: ref || null })}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="rs-every">
            Regenerate
          </label>
          <div className="gh-inline">
            <select
              id="rs-every"
              className="select"
              value={form.every}
              onChange={(e) => set({ every: e.target.value as Every })}
            >
              {EVERY.map((e) => (
                <option key={e.value} value={e.value}>
                  {e.label}
                </option>
              ))}
            </select>
            {form.every && (
              <input
                type="time"
                className="input"
                aria-label="Time (UTC)"
                value={form.time}
                onChange={(e) => set({ time: e.target.value || '03:00' })}
              />
            )}
          </div>
          {form.every && (
            <div className="hint">
              At {form.time} UTC. A run whose resume hasn&apos;t changed stops early, with no model
              call.
            </div>
          )}
        </div>
        {form.every && (
          <label className="gh-toggle rs-dataset-wide">
            <input
              type="checkbox"
              checked={form.publish}
              onChange={(e) => set({ publish: e.target.checked })}
            />
            Publish what passes the checks at once, and keep the doubtful pairs for review
          </label>
        )}
      </div>

      <div className="card-foot rs-dataset-foot">
        <button
          type="submit"
          className="btn btn-outline"
          disabled={!dirty || !targetValid || save.isPending}
        >
          <Icon name={save.isPending ? 'loader' : 'check'} />
          {saved ? 'Save' : 'Save the settings'}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!saved || dirty || active || start.isPending}
          title={!saved || dirty ? 'Save the settings first' : undefined}
          onClick={generate}
        >
          <Icon name={start.isPending ? 'loader' : 'play'} />
          Generate a draft
        </button>
        <label className="gh-toggle">
          <input
            type="checkbox"
            checked={fullRefresh}
            onChange={(e) => setFullRefresh(e.target.checked)}
          />
          Regenerate every section
        </label>
        {saved && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={forget.isPending || active}
            onClick={() =>
              forget.mutate(undefined, {
                onSuccess: () => toast.success('Settings forgotten; the dataset stays'),
                onError: (error) => toast.error(error.message),
              })
            }
          >
            Forget the settings
          </button>
        )}
      </div>

      {(saved?.next_run_at || run.data) && (
        <div className="card-body rs-dataset-status">
          {saved?.next_run_at && (
            <div className="hint">
              Next scheduled run: {new Date(saved.next_run_at).toLocaleString()}
            </div>
          )}
          {run.data && <LatestRun run={run.data} target={saved?.target_repo ?? ''} />}
        </div>
      )}
    </form>
  )
}

/** A resume's Q&A dataset: where it publishes, in which language and on which
 * model, when it is regenerated by itself, and a draft generated now. */
export function ResumeDataset({ resume }: { resume: ResumeOut }) {
  const settings = useResumeDataset(resume.id)
  const hub = useHubDatasets()
  if (settings.error) {
    return <p className="hub-error">{settings.error.message}</p>
  }
  if (settings.isPending || hub.isPending) {
    return (
      <p className="hint" aria-busy="true">
        <Icon name="loader" className="animate-spin" /> Reading the dataset settings…
      </p>
    )
  }
  // Keyed on the saved version: a save or a forget starts the form over.
  return (
    <DatasetCard
      key={settings.data?.updated_at ?? 'new'}
      resume={resume}
      saved={settings.data ?? null}
      namespace={hub.data?.namespace}
    />
  )
}
