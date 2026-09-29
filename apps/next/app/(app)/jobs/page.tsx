'use client'

import Link from 'next/link'
import './jobs.css'
import { Icon } from '@/components/app/icon'
import { useAllDatasetRuns, useDatasets, useGenerateDataset } from '@/hooks'
import { useGenerateStore } from '@/stores/generate'

const GITHUB_SOURCE = 'github://'
// Same default as the /generate form — runs don't record their threshold.
const DEFAULT_SIMILARITY_THRESHOLD = 0.9

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

// Only GitHub runs can be replayed: the account is in the source URL, whereas
// an uploaded file (`file://…`) is not kept after its generation.
function githubUsernameOf(sourceUrl?: string | null): string | null {
  if (!sourceUrl?.startsWith(GITHUB_SOURCE)) return null
  return sourceUrl.slice(GITHUB_SOURCE.length) || null
}

export default function JobsPage() {
  const runsQuery = useAllDatasetRuns()
  const runs = runsQuery.data ?? []
  const { data: datasets } = useDatasets()
  const generateMutation = useGenerateDataset()

  // The generation (if any) running in this session — started from /generate
  // or re-run from the history below. The backend runs pipelines synchronously
  // per request — there is no server-side job queue to poll.
  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const generationError = useGenerateStore((state) => state.error)
  const liveSteps = useGenerateStore((state) => state.liveSteps)
  const pendingName = useGenerateStore((state) => state.pendingName)
  const isGenerating = generationStatus === 'pending'

  const rerun = (datasetName: string, githubUsername: string) => {
    const targetLanguage = datasets?.find((d) => d.name === datasetName)?.target_language ?? null
    generateMutation.mutate({
      source: 'github',
      githubUsername,
      name: datasetName,
      targetLanguage,
      similarityThreshold: DEFAULT_SIMILARITY_THRESHOLD,
      persist: true,
    })
  }

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
            disabled={runsQuery.isRefetching}
            type="button"
          >
            <Icon name="refresh" className={runsQuery.isRefetching ? 'animate-spin' : undefined} />
            Refresh
          </button>
          <Link className="btn btn-primary" href="/generate">
            <Icon name="plus" />
            New generation
          </Link>
        </div>
      </div>

      {generationStatus === 'error' && generationError && (
        <p className="hint" style={{ color: 'var(--destructive)', marginBottom: 12 }}>
          Last generation{pendingName ? ` of ${pendingName}` : ''} failed: {generationError}
        </p>
      )}

      {isGenerating ? (
        <div className="job">
          <div className="job-top">
            <span className="job-ic">
              <Icon name="sparkles" />
            </span>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8 }}>
                {pendingName ?? 'Generation'} · pipeline{' '}
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
            <div className="card-desc">Recorded runs — one row per generation.</div>
          </div>
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
          <table className="table">
            <thead>
              <tr>
                <th>Job</th>
                <th>Version</th>
                <th>Target</th>
                <th>Source</th>
                <th>Started</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const githubUsername = githubUsernameOf(run.source_url)
                const rerunningThis = isGenerating && pendingName === run.dataset
                return (
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
                      <span className="tag">
                        {run.run_name ?? (run.version != null ? `v${run.version}` : '—')}
                      </span>
                    </td>
                    <td className="muted">
                      {run.item_count != null ? `${run.item_count} pairs` : '—'}
                    </td>
                    <td
                      className="muted"
                      style={{
                        maxWidth: 220,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {run.source_url ?? '—'}
                    </td>
                    <td className="muted">{formatDate(run.created_at)}</td>
                    <td>
                      <span className="badge badge-success">
                        <span className="dot" />
                        Recorded
                      </span>
                    </td>
                    <td>
                      {githubUsername && (
                        <button
                          className="btn btn-outline btn-sm"
                          type="button"
                          disabled={isGenerating}
                          title={`Re-run generation for ${run.dataset} from github.com/${githubUsername}`}
                          onClick={() => rerun(run.dataset, githubUsername)}
                        >
                          <Icon
                            name={rerunningThis ? 'loader' : 'refresh'}
                            className={rerunningThis ? 'animate-spin' : undefined}
                          />
                          {rerunningThis ? 'Running…' : 'Re-run'}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
