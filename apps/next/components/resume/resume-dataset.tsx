'use client'

import Link from 'next/link'
import { useLocale, useTranslations } from 'next-intl'
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
  useModels,
  useResumeDataset,
  useRunResumeDataset,
  useSaveResumeDataset,
} from '@/hooks'
import { SchedulePicker } from '@/components/jobs/schedule-picker'
import { rich, richLink } from '@/lib/rich'
import {
  type DatasetForm,
  initialForm,
  isDirty,
  runMetric,
  shownMetric,
  toSettings,
} from './dataset-state'

// The language choices; their labels are the `resume.dataset.languages.*` messages.
const LANGUAGES: NonNullable<ResumeDatasetIn['language']>[] = ['auto', 'en', 'fr']

const ACTIVE = new Set(['queued', 'running', 'publishing'])

/** The sections a run couldn't generate, and why (the model's error). */
function RunErrors({ run }: { run: JobRunOut }) {
  const t = useTranslations('resume')
  const errors = run.result?.errors ?? []
  if (errors.length === 0) return null
  return (
    <details className="job-errors" open>
      <summary className="hint job-error">{t('run.errors', { count: errors.length })}</summary>
      <ul className="job-error-list">
        {errors.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </details>
  )
}

/** The embedding model the duplicate and grounding checks use: one per
 * account, picked and measured on the Models page, not per dataset. */
function EmbeddingHint() {
  const t = useTranslations('resume')
  const { data } = useModels()
  if (!data) return null
  const model = data.embedding_model?.replace(/^openai:/, '')
  if (!model) {
    return <div className="hint">{t.rich('embedding.none', { link: richLink('/models') })}</div>
  }
  return (
    <div className="hint">
      {t.rich('embedding.hint', {
        model,
        whose: data.embedding_chosen ? t('embedding.yours') : t('embedding.server'),
        measured: data.embedding_calibration ? t('embedding.measured') : t('embedding.notMeasured'),
        mono: rich.mono,
        link: richLink('/models'),
      })}
    </div>
  )
}

function LatestRun({ run, target }: { run: JobRunOut; target: string }) {
  const t = useTranslations('resume')
  const tc = useTranslations('common')
  const locale = useLocale()
  const cancel = useCancelJobRun(run.id)
  if (run.status === 'queued' || run.status === 'running') {
    const { done = 0, total = 0, label = '' } = run.progress ?? {}
    const pct = total > 0 ? Math.round((done / total) * 100) : 4
    return (
      <div className="gh-run">
        <div className="hint">
          {run.status === 'queued'
            ? t('run.queued')
            : total > 0
              ? label
                ? t('run.generatingLabel', { done, total, label })
                : t('run.generating', { done, total })
              : label || t('reading')}
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
          {run.cancel_requested ? t('run.cancelling') : tc('cancel')}
        </button>
      </div>
    )
  }
  if (run.status === 'publishing') {
    return <div className="gh-run hint">{t('run.publishing')}</div>
  }
  const metrics = (run.result?.metrics ?? []) as [string, unknown][]
  const unchanged = metrics[0]?.[0] === 'Unchanged'
  const when = run.finished_at ? new Date(run.finished_at).toLocaleString(locale) : ''
  const link = richLink(datasetHref(target))
  if (run.status === 'succeeded' && run.preview) {
    const preview = run.preview
    const dropped = Number(runMetric(metrics, 'Dropped') ?? 0)
    const checks = shownMetric(run.result, 'Embedding checks')
    const embedding = runMetric(metrics, 'Embedding model')
    return (
      <div className="gh-run">
        {run.result?.url && (
          <div className="hint">
            {when
              ? t.rich('run.published', { date: when, link })
              : t.rich('run.publishedUndated', { link })}
          </div>
        )}
        <div className="gh-run-counts">
          <span>{t.rich('run.new', { count: preview.new.length, b: rich.b })}</span>
          <span>{t.rich('run.kept', { count: preview.kept, b: rich.b })}</span>
          {preview.review.length > 0 && (
            <span>{t.rich('run.heldOut', { count: preview.review.length, b: rich.b })}</span>
          )}
          {(preview.removed ?? []).length > 0 && (
            <span>{t.rich('run.removed', { count: preview.removed?.length ?? 0, b: rich.b })}</span>
          )}
          {dropped > 0 && (
            <span title={t('run.droppedTitle')}>
              {t.rich('run.dropped', { count: dropped, b: rich.b })}
            </span>
          )}
        </div>
        {checks != null && (
          <div className="hint">
            {embedding && embedding !== 'none'
              ? t('run.checksModel', {
                  model: String(embedding).replace(/^openai:/, ''),
                  result: checks,
                })
              : t('run.checks', { result: checks })}
          </div>
        )}
        <div className="gh-run-review">
          <span className="hint">
            {run.result?.url ? t('run.heldOutReview') : t('run.draftReady')}
          </span>
          <Link className="btn btn-primary btn-sm" href={`/drafts/runs/${run.id}`}>
            <Icon name="eye" />
            {t('run.review')}
          </Link>
        </div>
        <RunErrors run={run} />
      </div>
    )
  }
  if (run.status === 'published' || (run.status === 'succeeded' && run.result?.url)) {
    const date = run.published_at ? new Date(run.published_at).toLocaleString(locale) : when
    return (
      <div className="gh-run">
        <div className="hint">
          {date
            ? t.rich('run.published', { date, link })
            : t.rich('run.publishedUndated', { link })}
        </div>
        <RunErrors run={run} />
      </div>
    )
  }
  if (run.status === 'succeeded' && unchanged) {
    return (
      <div className="gh-run hint">
        {when ? t('run.unchanged', { date: when }) : t('run.unchangedUndated')}
      </div>
    )
  }
  return (
    <div className="gh-run hint job-error">
      {run.status === 'cancelled'
        ? t('run.cancelled')
        : run.status === 'interrupted'
          ? t('run.interrupted')
          : t('run.failed', { error: run.error ?? t('run.unknownError') })}
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
  const t = useTranslations('resume')
  const tc = useTranslations('common')
  const tj = useTranslations('jobs')
  const locale = useLocale()
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
      onSuccess: () => toast.success(t('dataset.saved')),
      onError: (error) => toast.error(error.message),
    })
  }

  const generate = () =>
    start.mutate(fullRefresh, {
      onSuccess: () => toast.success(t('dataset.queued')),
      onError: (error) => toast.error(error.message),
    })

  return (
    <form className="card rs-dataset" onSubmit={submit}>
      <div className="card-head">
        <div>
          <div className="card-title">{t('dataset.title')}</div>
          <p className="card-desc">{t('dataset.description')}</p>
        </div>
      </div>

      <div className="card-body rs-dataset-grid">
        <div className="field">
          <label className="label" htmlFor="rs-target">
            {t('dataset.publishesTo')}
          </label>
          <input
            id="rs-target"
            className="input mono"
            value={form.target_repo}
            aria-invalid={!targetValid}
            onChange={(e) => set({ target_repo: e.target.value })}
          />
          {!targetValid && <div className="hint job-error">{t('dataset.targetInvalid')}</div>}
        </div>
        <div className="field">
          <label className="label" htmlFor="rs-language">
            {t('dataset.language')}
          </label>
          <select
            id="rs-language"
            className="select"
            value={form.language}
            onChange={(e) => set({ language: e.target.value as DatasetForm['language'] })}
          >
            {LANGUAGES.map((language) => (
              <option key={language} value={language}>
                {t(`dataset.languages.${language}`)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="label" htmlFor="rs-model">
            {t('dataset.model')}
          </label>
          <ModelSelect
            id="rs-model"
            className="select"
            value={form.model_ref ?? ''}
            onChange={(ref) => set({ model_ref: ref || null })}
          />
          <EmbeddingHint />
        </div>
        <div className="rs-dataset-wide">
          <SchedulePicker
            id="rs-every"
            form={form}
            publishLabel={tj('schedule.publishDraft')}
            skipped={saved?.skipped}
            onChange={set}
          >
            {t('dataset.scheduleHint', { time: form.time })}
          </SchedulePicker>
        </div>
      </div>

      <div className="card-foot rs-dataset-foot">
        <button
          type="submit"
          className="btn btn-outline"
          disabled={!dirty || !targetValid || save.isPending}
        >
          <Icon name={save.isPending ? 'loader' : 'check'} />
          {saved ? tc('save') : t('dataset.saveSettings')}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!saved || dirty || active || start.isPending}
          title={!saved || dirty ? t('dataset.saveFirst') : undefined}
          onClick={generate}
        >
          <Icon name={start.isPending ? 'loader' : 'play'} />
          {t('dataset.generate')}
        </button>
        <label className="gh-toggle">
          <input
            type="checkbox"
            checked={fullRefresh}
            onChange={(e) => setFullRefresh(e.target.checked)}
          />
          {t('dataset.fullRefresh')}
        </label>
        {saved && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={forget.isPending || active}
            onClick={() =>
              forget.mutate(undefined, {
                onSuccess: () => toast.success(t('dataset.forgotten')),
                onError: (error) => toast.error(error.message),
              })
            }
          >
            {t('dataset.forget')}
          </button>
        )}
      </div>

      {(saved?.next_run_at || run.data) && (
        <div className="card-body rs-dataset-status">
          {saved?.next_run_at && (
            <div className="hint">
              {t('dataset.nextRun', { date: new Date(saved.next_run_at).toLocaleString(locale) })}
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
  const t = useTranslations('resume')
  const settings = useResumeDataset(resume.id)
  const hub = useHubDatasets()
  if (settings.error) {
    return <p className="hub-error">{settings.error.message}</p>
  }
  if (settings.isPending || hub.isPending) {
    return (
      <p className="hint" aria-busy="true">
        <Icon name="loader" className="animate-spin" /> {t('dataset.loading')}
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
