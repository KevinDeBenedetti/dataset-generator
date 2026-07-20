'use client'

import Link from 'next/link'
import './jobs.css'
import { Icon } from '@/components/app/icon'
import { useAllDatasetRuns } from '@/hooks'
import { useGenerateStore } from '@/stores/generate'

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

export default function JobsPage() {
  const runsQuery = useAllDatasetRuns()
  const runs = runsQuery.data ?? []

  // The live generation (if any) streamed by the /generate page in this
  // session. The backend runs pipelines synchronously per request — there is
  // no server-side job queue to poll.
  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const liveSteps = useGenerateStore((state) => state.liveSteps)
  const dataset = useGenerateStore((state) => state.dataset)

  const runningName = dataset
    ? 'dataset_name' in dataset
      ? dataset.dataset_name
      : dataset.name
    : null

  const notConfigured =
    runsQuery.error instanceof Error && /not configured/i.test(runsQuery.error.message)

  return (
    <div className="jobs-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Jobs &amp; batch</h1>
          <p className="page-sub">
            The generation running in this session and every recorded generation run.
          </p>
        </div>
        <div className="page-actions">
          <button
            className="btn btn-outline"
            onClick={() => runsQuery.refetch()}
            disabled={runsQuery.isFetching}
            type="button"
          >
            <Icon name="refresh" className={runsQuery.isFetching ? 'animate-spin' : undefined} />
            Refresh
          </button>
          <Link className="btn btn-primary" href="/generate">
            <Icon name="plus" />
            New generation
          </Link>
        </div>
      </div>

      {generationStatus === 'pending' ? (
        <div className="job">
          <div className="job-top">
            <span className="job-ic">
              <Icon name="sparkles" />
            </span>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8 }}>
                {runningName ?? 'Generation'} · pipeline{' '}
                <span className="badge badge-info">
                  <span className="dot" />
                  Running
                </span>
              </div>
              <div
                className="muted"
                style={{ fontSize: 12, marginTop: 2, fontFamily: "'Geist Mono',monospace" }}
              >
                {liveSteps.length > 0
                  ? (liveSteps[liveSteps.length - 1].detail ??
                    liveSteps[liveSteps.length - 1].label)
                  : 'Starting…'}
              </div>
            </div>
          </div>
          <div className="job-stages">
            {liveSteps.map((step) => (
              <div
                className={`stage${step.status === 'success' ? ' done' : step.status === 'error' ? '' : ' run'}`}
                key={`${step.key}-${step.label}`}
              >
                {step.label}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="card-body" style={{ paddingTop: 20 }}>
            <p className="muted">
              No generation running in this session.{' '}
              <Link href="/generate" style={{ textDecoration: 'underline' }}>
                Start one from the Generation page.
              </Link>
            </p>
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 22 }}>
        <div className="card-head">
          <div>
            <div className="card-title">Generation history</div>
            <div className="card-desc">
              Versioned runs recorded in Langfuse — one row per generation.
            </div>
          </div>
        </div>
        {runsQuery.isLoading && (
          <div className="card-body">
            <p className="muted">Loading runs…</p>
          </div>
        )}
        {!runsQuery.isLoading && notConfigured && (
          <div className="card-body">
            <p className="muted">
              Langfuse is not configured — set <code>LANGFUSE_*</code> in your <code>.env</code> to
              record and list generation runs.
            </p>
          </div>
        )}
        {!runsQuery.isLoading && runsQuery.error && !notConfigured && (
          <div className="card-body">
            <p className="hint" style={{ color: 'var(--destructive)' }}>
              {runsQuery.error instanceof Error
                ? runsQuery.error.message
                : 'Failed to load generation runs'}
            </p>
          </div>
        )}
        {!runsQuery.isLoading && !runsQuery.error && runs.length === 0 && (
          <div className="card-body">
            <p className="muted">No generation runs recorded yet.</p>
          </div>
        )}
        {runs.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Job</th>
                <th>Version</th>
                <th>Target</th>
                <th>Source</th>
                <th>Started</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={`${run.dataset}-${run.run_name ?? run.version}`}>
                  {/* oxlint-disable-next-line jsx-a11y/control-has-associated-label --
                      false positive: static, non-interactive cell; the icon is
                      already aria-hidden (see Icon) and the cell has visible
                      accessible text (run.dataset). */}
                  <td>
                    <div className="cell-main">
                      <span className="cell-ic">
                        <Icon name="sparkles" />
                      </span>
                      <div className="cell-title">{run.dataset} · generation</div>
                    </div>
                  </td>
                  <td>
                    <span className="tag">{run.run_name ?? (run.version != null ? `v${run.version}` : '—')}</span>
                  </td>
                  <td className="muted">
                    {run.item_count != null ? `${run.item_count} pairs` : '—'}
                  </td>
                  <td className="muted" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {run.source_url ?? '—'}
                  </td>
                  <td className="muted">{formatDate(run.created_at)}</td>
                  <td>
                    <span className="badge badge-success">
                      <span className="dot" />
                      Recorded
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
