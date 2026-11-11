'use client'

import Link from 'next/link'
import { Icon } from '@/components/app/icon'
import { useAllDatasetRuns } from '@/hooks'

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

// Every recorded generation run, newest first — one row per run.
export function RecentRuns() {
  const runsQuery = useAllDatasetRuns()
  const runs = runsQuery.data ?? []

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Recent runs</div>
          <div className="card-desc">Recorded generations — one row per run.</div>
        </div>
        <button
          className="btn btn-outline btn-sm"
          onClick={() => runsQuery.refetch()}
          disabled={runsQuery.isRefetching}
          type="button"
        >
          <Icon name="refresh" className={runsQuery.isRefetching ? 'animate-spin' : undefined} />
          Refresh
        </button>
      </div>
      {runsQuery.isPending && (
        <div className="card-body">
          <p className="muted">Loading runs…</p>
        </div>
      )}
      {!runsQuery.isPending && runsQuery.error && (
        <div className="card-body">
          <p className="hint" style={{ color: 'var(--destructive)' }}>
            {runsQuery.error instanceof Error
              ? runsQuery.error.message
              : 'Failed to load generation runs'}
          </p>
        </div>
      )}
      {!runsQuery.isPending && !runsQuery.error && runs.length === 0 && (
        <div className="card-body">
          <p className="muted">No generation runs recorded yet.</p>
        </div>
      )}
      {runs.length > 0 && (
        <table className="table stack-table">
          <thead>
            <tr>
              <th>Dataset</th>
              <th>Version</th>
              <th>Pairs</th>
              <th>Source</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={`${run.dataset}-${run.run_name ?? run.version}`}>
                <td data-label="Dataset">
                  <Link href={`/drafts/${encodeURIComponent(run.dataset)}`} className="cell-title">
                    {run.dataset}
                  </Link>
                </td>
                <td data-label="Version">
                  <span className="tag">
                    {run.run_name ?? (run.version != null ? `v${run.version}` : '—')}
                  </span>
                </td>
                <td className="muted" data-label="Pairs">
                  {run.item_count ?? '—'}
                </td>
                {/* Cut to one line on wide screens (full URL on hover); the
                    stacked phone layout shows it whole. */}
                <td
                  className="muted run-source"
                  title={run.source_url ?? undefined}
                  data-label="Source"
                >
                  {run.source_url ?? '—'}
                </td>
                <td className="muted" data-label="Started">
                  {formatDate(run.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
