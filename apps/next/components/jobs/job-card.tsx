'use client'

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import './jobs.css'
import { Icon } from '@/components/app/icon'
import { ModelSelect } from '@/components/app/model-select'
import {
  useCancelJobRun,
  useJobRun,
  useJobSchedule,
  usePublishJobRun,
  useSaveJobSchedule,
  useStartJobRun,
} from '@/hooks'
import { SchedulePicker } from './schedule-picker'
import { type ScheduleForm, differsFromCard, scheduleForm, toSchedule } from './schedule-state'
import type { DraftPair, JobInfo, JobRunOut } from '@/api/types'
import { richLink } from '@/lib/rich'

// The subset of JSON schema the job option models produce (pydantic).
interface OptionSchema {
  type?: string
  title?: string
  description?: string
  default?: unknown
  minimum?: number
  anyOf?: OptionSchema[]
  items?: { enum?: string[] }
}

type OptionValue = boolean | string | string[]

function Switch({
  on,
  onToggle,
  label,
  disabled,
}: {
  on: boolean
  onToggle: () => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      className={`switch${on ? ' on' : ''}`}
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
    />
  )
}

// Optional[int] comes through as anyOf [{type: integer}, {type: null}].
function kindOf(schema: OptionSchema): 'boolean' | 'integer' | 'enum-list' | 'other' {
  const type = schema.type ?? schema.anyOf?.find((s) => s.type && s.type !== 'null')?.type
  if (type === 'boolean') return 'boolean'
  if (type === 'integer' || type === 'number') return 'integer'
  if (type === 'array' && schema.items?.enum) return 'enum-list'
  return 'other'
}

function initialValues(properties: Record<string, OptionSchema>): Record<string, OptionValue> {
  const values: Record<string, OptionValue> = {}
  for (const [key, schema] of Object.entries(properties)) {
    const kind = kindOf(schema)
    if (kind === 'boolean') values[key] = schema.default === true
    else if (kind === 'enum-list') values[key] = (schema.default as string[]) ?? []
    else if (kind === 'integer') values[key] = schema.default == null ? '' : String(schema.default)
  }
  return values
}

// Form values → the options body: empty numbers are omitted (server default).
function toOptions(
  properties: Record<string, OptionSchema>,
  values: Record<string, OptionValue>,
): Record<string, unknown> {
  const options: Record<string, unknown> = {}
  for (const [key, schema] of Object.entries(properties)) {
    const value = values[key]
    if (kindOf(schema) === 'integer') {
      if (typeof value === 'string' && value.trim()) options[key] = Math.round(Number(value))
    } else if (value !== undefined) {
      options[key] = value
    }
  }
  return options
}

function OptionField({
  name,
  schema,
  value,
  onChange,
  disabled,
}: {
  name: string
  schema: OptionSchema
  value: OptionValue
  onChange: (value: OptionValue) => void
  disabled: boolean
}) {
  const t = useTranslations('jobs')
  const label = schema.title ?? name
  const kind = kindOf(schema)

  if (kind === 'boolean') {
    return (
      <div className="job-source-row">
        <div>
          <div className="label">{label}</div>
          {schema.description && <div className="hint">{schema.description}</div>}
        </div>
        <Switch
          on={value === true}
          onToggle={() => onChange(!value)}
          label={label}
          disabled={disabled}
        />
      </div>
    )
  }

  if (kind === 'integer') {
    const min = schema.minimum ?? schema.anyOf?.find((s) => s.minimum != null)?.minimum
    return (
      <div className="field">
        <label htmlFor={`opt-${name}`} className="label">
          {label}
        </label>
        <input
          id={`opt-${name}`}
          className="input"
          type="number"
          min={min}
          placeholder={t('serverDefault')}
          value={value as string}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
        />
        {schema.description && <div className="hint">{schema.description}</div>}
      </div>
    )
  }

  if (kind === 'enum-list') {
    const selected = new Set(value as string[])
    return (
      <div>
        <div className="label" style={{ marginBottom: 8 }}>
          {label}
        </div>
        <div className="job-source-list">
          {(schema.items?.enum ?? []).map((option) => (
            <div key={option} className="job-source-row">
              <div className="label mono">{option}</div>
              <Switch
                on={selected.has(option)}
                onToggle={() => {
                  const next = new Set(selected)
                  if (next.has(option)) next.delete(option)
                  else next.add(option)
                  onChange([...next])
                }}
                label={option}
                disabled={disabled}
              />
            </div>
          ))}
        </div>
      </div>
    )
  }

  return null
}

function Metrics({ run }: { run: JobRunOut }) {
  // The server translates them for display (an older client gets `metrics`).
  const shown = run.result?.metrics_display?.length
    ? run.result.metrics_display
    : (run.result?.metrics ?? [])
  const metrics = shown as [string, unknown][]
  if (metrics.length === 0) return null
  return (
    <div className="job-metrics">
      {metrics.map(([label, value]) => (
        <span key={label}>
          <span className="muted">{label}</span> <strong>{String(value)}</strong>
        </span>
      ))}
    </div>
  )
}

function Errors({ run }: { run: JobRunOut }) {
  const t = useTranslations('jobs')
  const errors = run.result?.errors ?? []
  if (errors.length === 0) return null
  return (
    <details className="job-errors">
      <summary className="hint">{t('errors', { count: errors.length })}</summary>
      <ul className="job-error-list">
        {errors.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </details>
  )
}

function PairRow({
  pair,
  checked,
  onToggle,
  disabled,
}: {
  pair: DraftPair
  checked: boolean
  onToggle: () => void
  disabled: boolean
}) {
  const t = useTranslations('jobs')
  return (
    <label className={`draft-row${checked ? '' : ' off'}`} aria-label={pair.question}>
      <input
        type="checkbox"
        className="size-4 accent-primary"
        checked={checked}
        onChange={onToggle}
        disabled={disabled}
      />
      <div style={{ minWidth: 0 }}>
        <div className="draft-q">{pair.question}</div>
        <div className="draft-a">{pair.answer}</div>
        <div className="draft-meta">
          {pair.repo && <span className="tag mono">{pair.repo}</span>}
          {pair.category && <span className="muted">{pair.category}</span>}
          {pair.grounding != null && (
            <span className="muted">
              {t('grounding', { percent: (pair.grounding * 100).toFixed(0) })}
            </span>
          )}
        </div>
      </div>
    </label>
  )
}

function toggled(set: Set<string>, id?: string | null): Set<string> {
  const next = new Set(set)
  if (!id) return next
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

// Step 2–3: review what a run generated, then publish exactly that.
function DraftReview({ run }: { run: JobRunOut }) {
  const t = useTranslations('jobs')
  const preview = run.preview
  const [excluded, setExcluded] = useState<Set<string>>(new Set())
  const [promoted, setPromoted] = useState<Set<string>>(new Set())
  const publish = usePublishJobRun(run.id)

  if (!preview) return null
  const newCount = preview.new.length - excluded.size + promoted.size
  const total = preview.kept + newCount
  const busy = publish.isPending

  const onPublish = () =>
    publish.mutate(
      { exclude: [...excluded], promote: [...promoted] },
      {
        onSuccess: () => toast.success(t('draft.published')),
        onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
      },
    )

  return (
    <div className="job-result">
      <div className="label" style={{ marginBottom: 4 }}>
        {t('draft.title')}
      </div>
      <p className="hint" style={{ marginBottom: 10 }}>
        {preview.review.length > 0
          ? t('draft.summaryHeld', {
              kept: preview.kept,
              added: preview.new.length,
              held: preview.review.length,
            })
          : t('draft.summary', { kept: preview.kept, added: preview.new.length })}
      </p>

      {preview.new.length === 0 && preview.review.length === 0 && (
        <p className="muted" style={{ marginBottom: 10 }}>
          {t('draft.unchanged')}
        </p>
      )}

      {preview.new.length > 0 && (
        <div className="draft-section">
          <div className="draft-head">
            <span className="label">{t('draft.newPairs')}</span>
            <span className="hint">
              {t('draft.selected', {
                selected: preview.new.length - excluded.size,
                total: preview.new.length,
              })}
            </span>
          </div>
          <div className="draft-list">
            {preview.new.map((pair) => (
              <PairRow
                key={pair.id ?? pair.question}
                pair={pair}
                checked={!excluded.has(pair.id ?? '')}
                onToggle={() => setExcluded((s) => toggled(s, pair.id))}
                disabled={busy}
              />
            ))}
          </div>
        </div>
      )}

      {preview.review.length > 0 && (
        <div className="draft-section">
          <div className="draft-head">
            <span className="label">{t('draft.toReview')}</span>
            <span className="hint">
              {t('draft.included', { included: promoted.size, total: preview.review.length })}
            </span>
          </div>
          <div className="draft-list">
            {preview.review.map((pair) => (
              <PairRow
                key={pair.id ?? pair.question}
                pair={pair}
                checked={promoted.has(pair.id ?? '')}
                onToggle={() => setPromoted((s) => toggled(s, pair.id))}
                disabled={busy}
              />
            ))}
          </div>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <button
          className="btn btn-primary"
          type="button"
          disabled={busy || total === 0}
          onClick={onPublish}
        >
          <Icon name={busy ? 'loader' : 'upload'} className={busy ? 'animate-spin' : undefined} />
          {busy ? t('draft.publishing') : t('draft.publish', { count: total })}
        </button>
        {preview.repo_id && (
          <span className="hint mono" title="HF_QA_DATASET_REPO">
            {t('draft.target', { repo: preview.repo_id })}
          </span>
        )}
      </div>
    </div>
  )
}

// The state of the job's current (or latest) run.
function CancelButton({ runId, requested }: { runId: string; requested: boolean }) {
  const t = useTranslations('jobs')
  const tc = useTranslations('common')
  const cancel = useCancelJobRun(runId)
  return (
    <button
      className="btn btn-outline btn-sm"
      type="button"
      disabled={requested || cancel.isPending}
      onClick={() => cancel.mutate()}
    >
      {requested ? t('run.stopping') : tc('cancel')}
    </button>
  )
}

function RunPanel({ runId }: { runId: string }) {
  const t = useTranslations('jobs')
  const locale = useLocale()
  const { data: run, error } = useJobRun(runId)
  if (error) {
    return (
      <p className="hint job-error">{error instanceof Error ? error.message : String(error)}</p>
    )
  }
  if (!run) return null

  if (run.status === 'queued') {
    return (
      <div className="job-result">
        <div className="hint" style={{ marginBottom: 6 }}>
          {t('run.queued')}
        </div>
        <CancelButton runId={run.id} requested={!!run.cancel_requested} />
      </div>
    )
  }

  if (run.status === 'publishing') {
    return (
      <div className="job-result">
        <div className="hint">{t('run.publishing')}</div>
      </div>
    )
  }

  if (run.status === 'running') {
    const { done = 0, total = 0, label = '' } = run.progress ?? {}
    const pct = total > 0 ? Math.round((done / total) * 100) : 0
    return (
      <div className="job-result">
        <div className="hint" style={{ marginBottom: 6 }}>
          {total > 0
            ? `${t('run.generating', { done, total })}${label ? ` · ${label}` : ''}`
            : label || t('run.fetching')}
        </div>
        <div className="job-progress">
          <div style={{ width: `${total > 0 ? pct : 5}%` }} />
        </div>
        <p className="hint" style={{ marginTop: 6 }}>
          {t('run.background')}
        </p>
        <CancelButton runId={run.id} requested={!!run.cancel_requested} />
      </div>
    )
  }

  if (run.status === 'failed' || run.status === 'interrupted' || run.status === 'cancelled') {
    return (
      <div className="job-result">
        <p className="hint job-error">
          {run.status === 'cancelled'
            ? t('run.cancelled')
            : run.status === 'interrupted'
              ? t('run.interrupted')
              : t('run.failed', { error: String(run.error) })}
        </p>
      </div>
    )
  }

  if (run.status === 'published') {
    return (
      <div className="job-result">
        <div className="hint" style={{ marginBottom: 6 }}>
          {run.published_at
            ? t('run.publishedAt', { date: new Date(run.published_at).toLocaleString(locale) })
            : t('run.published')}{' '}
          {run.published_url && (
            <a href={run.published_url} target="_blank" rel="noopener noreferrer">
              {t('run.viewOnHub')}
              <Icon name="external" className="ic-sm" />
            </a>
          )}
        </div>
        <Metrics run={run} />
        <Errors run={run} />
      </div>
    )
  }

  // succeeded
  if (run.has_draft) {
    return (
      <>
        <div className="job-result">
          <Metrics run={run} />
          <Errors run={run} />
        </div>
        <DraftReview key={run.id} run={run} />
      </>
    )
  }
  return (
    <div className="job-result">
      <div className="hint" style={{ marginBottom: 6 }}>
        {run.result?.dry_run ? t('run.dryRun') : t('run.published')}{' '}
        {run.published_url && (
          <a href={run.published_url} target="_blank" rel="noopener noreferrer">
            {t('run.viewOnHub')}
            <Icon name="external" className="ic-sm" />
          </a>
        )}
      </div>
      <Metrics run={run} />
      <Errors run={run} />
    </div>
  )
}

/** When the job runs by itself, with the options and the model the card
 * shows at the moment the schedule is set or changed. */
function JobSchedule({
  job,
  options,
  modelRef,
}: {
  job: JobInfo
  options: () => Record<string, unknown>
  modelRef: string | null
}) {
  const t = useTranslations('jobs')
  const locale = useLocale()
  const saved = useJobSchedule(job.id)
  const save = useSaveJobSchedule(job.id)
  const form = scheduleForm(saved.data)
  const store = (patch: Partial<ScheduleForm> = {}) => {
    const timing = toSchedule({ ...form, ...patch })
    save.mutate(timing && { ...timing, options: options(), model_ref: modelRef }, {
      onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
    })
  }
  const stale = saved.data != null && differsFromCard(saved.data, { options: options(), modelRef })

  if (saved.isPending) return null
  return (
    <>
      {stale && (
        <div className="hint job-config-hint">
          {job.uses_model ? t('schedule.staleModel') : t('schedule.stale')}{' '}
          <button
            type="button"
            className="btn btn-outline btn-sm"
            disabled={save.isPending}
            onClick={() => store()}
          >
            {t('schedule.replace')}
          </button>
        </div>
      )}
      <SchedulePicker
        id={`every-${job.id}`}
        form={form}
        disabled={save.isPending}
        publishLabel={job.has_draft ? t('schedule.publishDraft') : t('schedule.publishBuilt')}
        skipped={saved.data?.skipped}
        onChange={(patch: Partial<ScheduleForm>) => store(patch)}
      >
        {job.uses_model
          ? t('schedule.hintModel', { time: form.time })
          : t('schedule.hint', { time: form.time })}
        {job.has_draft && ` ${t('schedule.noChange')}`}
        {saved.data?.next_run_at &&
          ` ${t('schedule.nextRun', {
            date: new Date(saved.data.next_run_at).toLocaleString(locale),
          })}`}
      </SchedulePicker>
    </>
  )
}

/** One job of the catalogue (GET /jobs): its options, the button that queues a
 * run, and that run's state — with the review of its draft for a draft job. */
export function JobCard({ job }: { job: JobInfo }) {
  const t = useTranslations('jobs')
  const properties = (job.options_schema.properties ?? {}) as Record<string, OptionSchema>
  const [values, setValues] = useState(() => initialValues(properties))
  const [modelRef, setModelRef] = useState('')
  const [startedRunId, setStartedRunId] = useState<string | null>(null)
  const start = useStartJobRun(job.id)
  const runId = startedRunId ?? job.latest_run?.id ?? null
  const { data: run } = useJobRun(runId)
  const running = start.isPending || ['queued', 'running', 'publishing'].includes(run?.status ?? '')

  const onStart = () =>
    start.mutate(
      {
        options: toOptions(properties, values),
        modelRef: job.uses_model ? modelRef || null : null,
      },
      {
        onSuccess: (r) => setStartedRunId(r.id),
        onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
      },
    )

  const startLabel = job.has_draft
    ? t('start.draft')
    : values.dry_run === true
      ? t('start.dryRun')
      : t('start.publish')

  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">{job.title}</div>
        <span className={`badge badge-${job.configured ? 'success' : 'destructive'}`}>
          <span className="dot" />
          {job.configured ? t('configured') : t('notConfigured')}
        </span>
      </div>
      <div
        className="card-body"
        style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: 14 }}
      >
        <p className="hint">{job.description}</p>
        {(job.missing ?? []).length > 0 && (
          <p className="hint job-config-hint">
            {t.rich('missing', {
              missing: (job.missing ?? []).join(', '),
              link: richLink('/settings'),
            })}
          </p>
        )}

        {job.uses_model && (
          <div className="field">
            <label htmlFor={`model-${job.id}`} className="label">
              {t('model')}
            </label>
            <ModelSelect
              id={`model-${job.id}`}
              value={modelRef}
              onChange={setModelRef}
              disabled={running}
              className="input"
            />
          </div>
        )}

        {Object.entries(properties).map(([name, schema]) => (
          <OptionField
            key={name}
            name={name}
            schema={schema}
            value={values[name]}
            onChange={(value) => setValues((v) => ({ ...v, [name]: value }))}
            disabled={running}
          />
        ))}
        <JobSchedule
          job={job}
          options={() => toOptions(properties, values)}
          modelRef={job.uses_model ? modelRef || null : null}
        />
      </div>
      <div
        className="card-foot"
        style={{ flexDirection: 'column', alignItems: 'stretch', gap: 10 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            className={`btn ${job.has_draft && run?.status === 'succeeded' ? 'btn-outline' : 'btn-primary'}`}
            disabled={running}
            onClick={onStart}
            type="button"
          >
            <Icon
              name={running ? 'loader' : 'play'}
              className={running ? 'animate-spin' : undefined}
            />
            {running ? t('running') : startLabel}
          </button>
          {job.has_draft && !running && <span className="hint">{t('reviewFirst')}</span>}
        </div>
        {runId && <RunPanel runId={runId} />}
      </div>
    </div>
  )
}
