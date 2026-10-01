'use client'

import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'
import './jobs.css'
import { Icon } from '@/components/app/icon'
import { ModelSelect } from '@/components/app/model-select'
import { useCancelJobRun, useJobRun, useJobs, usePublishJobRun, useStartJobRun } from '@/hooks'
import type { DraftPair, JobInfo, JobRunOut } from '@/api/types'

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
          placeholder="Server default"
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
  const metrics = (run.result?.metrics ?? []) as [string, unknown][]
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
  const errors = run.result?.errors ?? []
  if (errors.length === 0) return null
  return (
    <details className="job-errors">
      <summary className="hint">
        {errors.length} non-fatal error(s) — those sources are retried next run
      </summary>
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
            <span className="muted">grounding {(pair.grounding * 100).toFixed(0)}%</span>
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
        onSuccess: () => toast.success('Published to Hugging Face'),
        onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
      },
    )

  return (
    <div className="job-result">
      <div className="label" style={{ marginBottom: 4 }}>
        Review the draft
      </div>
      <p className="hint" style={{ marginBottom: 10 }}>
        {preview.kept} pair(s) carried over unchanged, {preview.new.length} new
        {preview.review.length > 0
          ? `, ${preview.review.length} held out (answer far from its source — off by default)`
          : ''}
        . Untick what you don&apos;t want published.
      </p>

      {preview.new.length === 0 && preview.review.length === 0 && (
        <p className="muted" style={{ marginBottom: 10 }}>
          Nothing changed since the published version — no new pair.
        </p>
      )}

      {preview.new.length > 0 && (
        <div className="draft-section">
          <div className="draft-head">
            <span className="label">New pairs</span>
            <span className="hint">
              {preview.new.length - excluded.size}/{preview.new.length} selected
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
            <span className="label">To review</span>
            <span className="hint">
              {promoted.size}/{preview.review.length} included
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
          {busy ? 'Publishing…' : `Publish ${total} pairs to Hugging Face`}
        </button>
        {preview.repo_id && (
          <span className="hint mono" title="HF_QA_DATASET_REPO">
            → {preview.repo_id} (private)
          </span>
        )}
      </div>
    </div>
  )
}

// The state of the job's current (or latest) run.
function CancelButton({ runId, requested }: { runId: string; requested: boolean }) {
  const cancel = useCancelJobRun(runId)
  return (
    <button
      className="btn btn-outline btn-sm"
      type="button"
      disabled={requested || cancel.isPending}
      onClick={() => cancel.mutate()}
    >
      {requested ? 'Stopping…' : 'Cancel'}
    </button>
  )
}

function RunPanel({ runId }: { runId: string }) {
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
          Queued — waiting for a worker to pick it up.
        </div>
        <CancelButton runId={run.id} requested={!!run.cancel_requested} />
      </div>
    )
  }

  if (run.status === 'publishing') {
    return (
      <div className="job-result">
        <div className="hint">Publishing to Hugging Face…</div>
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
            ? `Generating… ${done}/${total} repos${label ? ` · ${label}` : ''}`
            : label || 'Fetching your GitHub repositories…'}
        </div>
        <div className="job-progress">
          <div style={{ width: `${total > 0 ? pct : 5}%` }} />
        </div>
        <p className="hint" style={{ marginTop: 6 }}>
          Runs on the server — you can leave this page and come back.
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
            ? 'The last run was cancelled.'
            : run.status === 'interrupted'
              ? 'The last run was interrupted (its worker stopped). Start it again.'
              : `The last run failed: ${run.error}`}
        </p>
      </div>
    )
  }

  if (run.status === 'published') {
    return (
      <div className="job-result">
        <div className="hint" style={{ marginBottom: 6 }}>
          Published {run.published_at ? new Date(run.published_at).toLocaleString() : ''}.{' '}
          {run.published_url && (
            <a href={run.published_url} target="_blank" rel="noopener noreferrer">
              View on Hugging Face
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
        {run.result?.dry_run ? 'Dry run complete — nothing published.' : 'Published.'}{' '}
        {run.published_url && (
          <a href={run.published_url} target="_blank" rel="noopener noreferrer">
            View on Hugging Face
            <Icon name="external" className="ic-sm" />
          </a>
        )}
      </div>
      <Metrics run={run} />
      <Errors run={run} />
    </div>
  )
}

function JobCard({ job }: { job: JobInfo }) {
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
    ? 'Generate draft'
    : values.dry_run === true
      ? 'Run (dry run)'
      : 'Run & publish'

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{job.title}</div>
          <div className="card-desc">
            {job.schedule} via <code className="mono">{job.workflow}</code>
          </div>
        </div>
        <span className={`badge badge-${job.configured ? 'success' : 'destructive'}`}>
          <span className="dot" />
          {job.configured ? 'Configured' : 'Not configured'}
        </span>
      </div>
      <div
        className="card-body"
        style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: 14 }}
      >
        <p className="hint">{job.description}</p>
        {(job.missing ?? []).length > 0 && (
          <p className="hint job-config-hint">
            Not configured — add {(job.missing ?? []).join(', ')} in{' '}
            <Link href="/settings">Settings</Link>.
          </p>
        )}

        {job.uses_model && (
          <div className="field">
            <label htmlFor={`model-${job.id}`} className="label">
              Model
            </label>
            <ModelSelect
              id={`model-${job.id}`}
              value={modelRef}
              onChange={setModelRef}
              modelRole="jobs"
              disabled={running}
              className="input"
            />
            <div className="hint">
              Claude models bill against the subscription; OpenAI models against the API key.
            </div>
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
            {running ? 'Running…' : startLabel}
          </button>
          {job.has_draft && !running && (
            <span className="hint">Nothing is published until you review the draft.</span>
          )}
        </div>
        {runId && <RunPanel runId={runId} />}
      </div>
    </div>
  )
}

export default function JobsPage() {
  const jobsQuery = useJobs()

  return (
    <div className="jobs-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Jobs</h1>
          <p className="page-sub">
            Dataset jobs built from recurring sources. Each one runs on its GitHub Actions schedule
            and can be run here on demand — the same code either way.
          </p>
        </div>
        <div className="page-actions">
          <button
            className="btn btn-outline"
            onClick={() => jobsQuery.refetch()}
            disabled={jobsQuery.isRefetching}
            type="button"
          >
            <Icon name="refresh" className={jobsQuery.isRefetching ? 'animate-spin' : undefined} />
            Refresh status
          </button>
        </div>
      </div>

      {jobsQuery.error && (
        <p className="hint job-error" style={{ marginBottom: 18 }}>
          {jobsQuery.error instanceof Error ? jobsQuery.error.message : 'Failed to load the jobs'}
        </p>
      )}
      {jobsQuery.isPending && <p className="muted">Loading jobs…</p>}

      <div className="grid-2" style={{ alignItems: 'start', gap: 24 }}>
        {(jobsQuery.data ?? []).map((job) => (
          <JobCard key={job.id} job={job} />
        ))}
      </div>
    </div>
  )
}
