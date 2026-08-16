'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
// The design's detail-page styles (.qa, .ver, .tabpane) live with the static
// mockup; this is the real, data-backed page wearing the same skin.
import '../../dataset-detail/dataset-detail.css'
import { Icon } from '@/components/app/icon'
import { QAList, PaginationWrapper } from '@/components/dataset'
import { useDatasets, useDatasetSources } from '@/hooks'
import { useQAByDataset } from '@/hooks/use-qa'
import { relativeTime } from '@/lib/utils'
import type { DatasetAnalysis, DatasetSource } from '@/api/types'

const PAGE_SIZE = 10

type TabKey = 'pairs' | 'sources' | 'history'

// Sources are recorded as a URL whose scheme says where they came from (see
// _source_label_kind server-side); the icon follows that kind. `kind` is a
// plain string in the schema, so an unlisted one falls back rather than
// rendering a blank icon.
const KIND_ICON: Record<string, string> = {
  web: 'globe',
  file: 'fileText',
  github: 'github',
  unknown: 'help',
}

function kindIcon(kind: string): string {
  return KIND_ICON[kind] ?? 'globe'
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

// A source row links out only when it's a real URL — file:// and github://
// are internal markers, not addresses a browser can open.
function SourceCell({ source }: { source: DatasetSource }) {
  const isWeb = source.kind === 'web' && !!source.url
  return (
    <div className="cell-main">
      <span className="cell-ic">
        <Icon name={kindIcon(source.kind)} />
      </span>
      <div className="cell-title">
        {isWeb ? (
          <a href={source.url as string} target="_blank" rel="noopener noreferrer">
            {source.label}
          </a>
        ) : (
          source.label
        )}
      </div>
    </div>
  )
}

// One analysis = one recorded generation run: what was analysed, and what it
// produced. Missing stats stay blank rather than reading as a zero.
function analysisDetail(analysis: DatasetAnalysis): string {
  const parts: string[] = [`Analysed ${analysis.label}`]
  if (analysis.pages_analyzed != null) {
    parts.push(`${analysis.pages_analyzed} page(s) read`)
  }
  if (analysis.new_pairs != null) {
    parts.push(`+${analysis.new_pairs} pairs`)
  }
  if (analysis.duplicates_skipped != null) {
    parts.push(`${analysis.duplicates_skipped} duplicate(s) skipped`)
  }
  return parts.join(' · ')
}

export default function DatasetDetailPage() {
  const params = useParams()
  // Datasets are keyed by their Langfuse name (URL-encoded in the route).
  const datasetName = decodeURIComponent(params.id as string)

  const [tab, setTab] = useState<TabKey>('pairs')
  const [page, setPage] = useState(1)

  const { data: datasets, isPending: datasetsPending } = useDatasets()
  const dataset = useMemo(
    () => datasets?.find((d) => d.name === datasetName) ?? null,
    [datasets, datasetName],
  )

  const { data: qaResponse, isLoading: qaLoading } = useQAByDataset(datasetName, {
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    enabled: !!datasetName,
  })

  const sourcesQuery = useDatasetSources(datasetName)
  const sources = sourcesQuery.data?.sources ?? []
  const history = sourcesQuery.data?.history ?? []

  const totalPages = Math.ceil((qaResponse?.total_count ?? 0) / (qaResponse?.limit || PAGE_SIZE))
  const now = Date.now()

  // Langfuse may not be configured at all (503) — that reads differently from
  // a real upstream failure, here as on /datasets.
  const sourcesNotConfigured =
    sourcesQuery.error instanceof Error && /not configured/i.test(sourcesQuery.error.message)

  const addSourceHref = `/generate?dataset=${encodeURIComponent(datasetName)}`

  const latestVersion = history[0]?.version ?? null

  return (
    <div className="dd-page">
      <Link
        href="/datasets"
        className="btn btn-ghost btn-sm"
        style={{ margin: '-4px 0 14px', paddingLeft: 6 }}
      >
        <Icon name="chevronLeft" />
        Datasets
      </Link>

      <div className="page-head">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="cell-ic ic-lg" style={{ width: 42, height: 42, borderRadius: 10 }}>
              <Icon name="database" className="ic-lg" />
            </span>
            <div>
              <h1 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {datasetName}
                {latestVersion != null && <span className="tag">v{latestVersion}</span>}
              </h1>
              <p className="page-sub" style={{ marginTop: 3 }}>
                {qaResponse?.total_count ?? '—'} Q/A pairs · {sources.length} source(s) ·{' '}
                {history.length} analysis run(s)
                {dataset?.target_language ? ` · language ${dataset.target_language}` : ''}
              </p>
            </div>
          </div>
        </div>
        <div className="page-actions">
          <button
            className="btn btn-outline"
            type="button"
            onClick={() => sourcesQuery.refetch()}
            disabled={sourcesQuery.isFetching}
          >
            <Icon name="refresh" className={sourcesQuery.isFetching ? 'animate-spin' : undefined} />
            Refresh
          </button>
          <Link className="btn btn-primary" href={addSourceHref}>
            <Icon name="plus" />
            Add a source
          </Link>
        </div>
      </div>

      {datasetsPending && !dataset && (
        <p className="muted" style={{ marginBottom: 14 }}>
          Loading dataset…
        </p>
      )}
      {dataset?.description && (
        <p className="muted" style={{ marginBottom: 14 }}>
          {dataset.description}
        </p>
      )}

      <div className="tabs" style={{ marginBottom: 20 }}>
        <button
          type="button"
          className={`tab${tab === 'pairs' ? ' active' : ''}`}
          onClick={() => setTab('pairs')}
        >
          Q/A pairs <span className="mono muted">{qaResponse?.total_count ?? 0}</span>
        </button>
        <button
          type="button"
          className={`tab${tab === 'sources' ? ' active' : ''}`}
          onClick={() => setTab('sources')}
        >
          Sources <span className="mono muted">{sources.length}</span>
        </button>
        <button
          type="button"
          className={`tab${tab === 'history' ? ' active' : ''}`}
          onClick={() => setTab('history')}
        >
          History <span className="mono muted">{history.length}</span>
        </button>
      </div>

      {tab === 'pairs' && (
        <div className="tabpane active">
          <div className="card">
            <div className="card-body">
              {qaLoading ? (
                <p className="muted">Loading Q/A pairs…</p>
              ) : (
                <>
                  <QAList
                    qaData={qaResponse?.qa_data ?? []}
                    returnedCount={qaResponse?.returned_count ?? 0}
                  />
                  {totalPages > 1 && (
                    <PaginationWrapper
                      className="mt-6"
                      total={qaResponse?.total_count ?? 0}
                      currentPage={page}
                      itemsPerPage={qaResponse?.limit ?? PAGE_SIZE}
                      onPageChange={setPage}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === 'sources' && (
        <div className="tabpane active">
          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">Sources</div>
                <div className="card-desc">
                  Every origin that produced Q/A pairs in this dataset — one row per crawled page,
                  uploaded file or GitHub account.
                </div>
              </div>
              <Link className="btn btn-outline btn-sm" href={addSourceHref}>
                <Icon name="plus" />
                Add a source
              </Link>
            </div>

            {sourcesQuery.isPending && (
              <div className="card-body">
                <p className="muted">Loading sources…</p>
              </div>
            )}
            {!sourcesQuery.isPending && sourcesNotConfigured && (
              <div className="card-body">
                <p className="muted">
                  Langfuse is not configured — set <code>LANGFUSE_*</code> in your <code>.env</code>{' '}
                  to read a dataset&apos;s sources.
                </p>
              </div>
            )}
            {!sourcesQuery.isPending && sourcesQuery.error && !sourcesNotConfigured && (
              <div className="card-body">
                <p className="hint" style={{ color: 'var(--destructive)' }}>
                  {sourcesQuery.error instanceof Error
                    ? sourcesQuery.error.message
                    : 'Failed to load the dataset sources'}
                </p>
              </div>
            )}
            {!sourcesQuery.isPending && !sourcesQuery.error && sources.length === 0 && (
              <div className="card-body">
                <p className="muted">
                  No source recorded yet. <Link href={addSourceHref}>Add one</Link> to generate
                  pairs into this dataset.
                </p>
              </div>
            )}
            {sources.length > 0 && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Type</th>
                    <th>Q/A pairs</th>
                    <th>First seen</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map((source) => (
                    <tr key={source.url ?? source.label}>
                      {/* oxlint-disable-next-line jsx-a11y/control-has-associated-label --
                          false positive: static cell; the icon is aria-hidden (see
                          Icon) and the cell has visible accessible text (the label). */}
                      <td>
                        <SourceCell source={source} />
                      </td>
                      <td>
                        <span className="tag">{source.kind}</span>
                      </td>
                      <td className="mono">{source.qa_count}</td>
                      <td className="muted">{relativeTime(source.first_seen_at, now)}</td>
                      <td className="muted">{relativeTime(source.last_seen_at, now)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {tab === 'history' && (
        <div className="tabpane active">
          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">Analysis history</div>
                <div className="card-desc">
                  Every analysis recorded for this dataset, newest first — the seed that was read
                  and what it contributed.
                </div>
              </div>
            </div>
            <div className="card-body" style={{ paddingTop: 20 }}>
              {sourcesQuery.isPending && <p className="muted">Loading history…</p>}
              {!sourcesQuery.isPending && sourcesNotConfigured && (
                <p className="muted">Langfuse is not configured — analyses are recorded there.</p>
              )}
              {!sourcesQuery.isPending && !sourcesNotConfigured && history.length === 0 && (
                <p className="muted">
                  No analysis recorded yet. Runs are written when a generation syncs to Langfuse.
                </p>
              )}
              {history.map((analysis, index) => (
                <div
                  className={`ver${index === 0 ? ' cur' : ''}`}
                  key={analysis.run_name ?? `${analysis.version}-${analysis.created_at}`}
                >
                  <span className="vdot">
                    <Icon name={index === 0 ? 'sparkles' : 'gitBranch'} />
                  </span>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                      <b>
                        {analysis.run_name ??
                          (analysis.version != null ? `v${analysis.version}` : '—')}
                      </b>
                      {index === 0 && (
                        <span className="badge badge-success">
                          <span className="dot" />
                          Latest
                        </span>
                      )}
                      <span className="muted" style={{ fontSize: 12 }}>
                        {relativeTime(analysis.created_at, now)}
                      </span>
                      <span className="muted" style={{ fontSize: 12 }}>
                        {formatDate(analysis.created_at)}
                      </span>
                    </div>
                    <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                      {analysisDetail(analysis)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
