'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { errorStatus } from '@/api/sdk'
import type { HuggingFaceDataset } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { useHubDatasets } from '@/hooks'
import { cn } from '@/lib/utils'
import { datasetHref, formatBytes, formatCount, splitRepoId, timeAgo } from './format'

type Visibility = 'all' | 'private' | 'public'
type SortKey = 'updated' | 'name' | 'downloads' | 'likes' | 'size'

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'updated', label: 'Recently updated' },
  { key: 'name', label: 'Name' },
  { key: 'downloads', label: 'Most downloaded' },
  { key: 'likes', label: 'Most liked' },
  { key: 'size', label: 'Largest' },
]

// Hub tags that only restate metadata shown elsewhere on the card.
const NOISE_TAG = /^(region|library|format|modality|size_categories|task_categories|task_ids):/

function displayName(dataset: HuggingFaceDataset): string {
  return dataset.pretty_name || splitRepoId(dataset.id).name
}

function sortValue(dataset: HuggingFaceDataset, key: SortKey): number | string {
  switch (key) {
    case 'name':
      return displayName(dataset).toLowerCase()
    case 'downloads':
      return -(dataset.downloads ?? 0)
    case 'likes':
      return -(dataset.likes ?? 0)
    case 'size':
      return -(dataset.used_storage ?? 0)
    default:
      return -new Date(dataset.last_modified ?? 0).getTime()
  }
}

function matches(dataset: HuggingFaceDataset, needle: string): boolean {
  if (!needle) return true
  const haystack = [dataset.id, dataset.pretty_name, dataset.description, ...(dataset.tags ?? [])]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return haystack.includes(needle)
}

function StatTile({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <div className="card stat">
      <div className="stat-top">
        <span className="stat-label">{label}</span>
        <span className="stat-ic">
          <Icon name={icon} />
        </span>
      </div>
      <div className="stat-val">{value}</div>
    </div>
  )
}

function DatasetCard({ dataset, now }: { dataset: HuggingFaceDataset; now: number }) {
  const tags = (dataset.tags ?? []).filter((t) => !NOISE_TAG.test(t) && !t.startsWith('language:'))
  const shown = tags.slice(0, 4)
  return (
    <Link href={datasetHref(dataset.id)} className="card hub-ds">
      <div className="hub-ds-top">
        <span className="cell-ic">
          <Icon name="database" />
        </span>
        <div className="hub-ds-title">
          <div className="hub-ds-name">{displayName(dataset)}</div>
          <div className="cell-sub">{dataset.id}</div>
        </div>
        {dataset.private ? (
          <span className="badge badge-secondary">
            <Icon name="key" className="ic-sm" />
            Private
          </span>
        ) : (
          <span className="badge badge-outline">
            <Icon name="globe" className="ic-sm" />
            Public
          </span>
        )}
      </div>
      {dataset.description && <p className="hub-ds-desc">{dataset.description}</p>}
      {(shown.length > 0 || dataset.language?.length || dataset.license) && (
        <div className="hub-ds-tags">
          {dataset.language?.map((lang) => (
            <span key={`lang-${lang}`} className="tag">
              {lang}
            </span>
          ))}
          {dataset.license && <span className="tag">{dataset.license}</span>}
          {shown.map((tag) => (
            <span key={tag} className="tag">
              {tag}
            </span>
          ))}
          {tags.length > shown.length && (
            <span className="tag muted">+{tags.length - shown.length}</span>
          )}
        </div>
      )}
      <div className="hub-ds-meta">
        <span title={dataset.last_modified ?? undefined}>
          <Icon name="clock" className="ic-sm" />
          {timeAgo(dataset.last_modified, now)}
        </span>
        {dataset.used_storage != null && (
          <span>
            <Icon name="layers" className="ic-sm" />
            {formatBytes(dataset.used_storage)}
          </span>
        )}
        {dataset.size_category && <span className="mono">{dataset.size_category}</span>}
        <span title="Downloads, last 30 days">
          <Icon name="download" className="ic-sm" />
          {formatCount(dataset.downloads ?? 0)}
        </span>
        <span title="Likes">
          <Icon name="star" className="ic-sm" />
          {formatCount(dataset.likes ?? 0)}
        </span>
      </div>
    </Link>
  )
}

/** Shown when the API answers 503: no Hugging Face token yet. */
export function ConnectHuggingFace({ message }: { message?: string }) {
  return (
    <div className="card hub-empty">
      <span className="cell-ic ic-lg">
        <Icon name="key" className="ic-lg" />
      </span>
      <div>
        <div className="card-title">Connect Hugging Face</div>
        <p className="card-desc">
          Datasets are read straight from the Hugging Face Hub, with your own access token.{' '}
          {message}
        </p>
      </div>
      <Link className="btn btn-primary" href="/settings">
        <Icon name="settings" />
        Open Settings
      </Link>
    </div>
  )
}

export function HubDatasetsList() {
  const [author, setAuthor] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [visibility, setVisibility] = useState<Visibility>('all')
  const [sort, setSort] = useState<SortKey>('updated')
  // One "now" per mount keeps relative times stable across renders.
  const [now] = useState(() => Date.now())
  const { data, isPending, error, refetch, isFetching, isPlaceholderData } = useHubDatasets(author)

  const all = useMemo(() => data?.datasets ?? [], [data])
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return all
      .filter((d) => matches(d, needle))
      .filter((d) => visibility === 'all' || (visibility === 'private') === d.private)
      .toSorted((a, b) => {
        const left = sortValue(a, sort)
        const right = sortValue(b, sort)
        return left < right ? -1 : left > right ? 1 : 0
      })
  }, [all, search, visibility, sort])

  const totals = useMemo(
    () => ({
      private: all.filter((d) => d.private).length,
      downloads: all.reduce((sum, d) => sum + (d.downloads ?? 0), 0),
      storage: all.reduce((sum, d) => sum + (d.used_storage ?? 0), 0),
    }),
    [all],
  )

  const status = errorStatus(error)

  return (
    <div className="hub-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Datasets</h1>
          <p className="page-sub">
            Every dataset is read from Hugging Face, the source of truth. Generated data waits in{' '}
            <Link href="/drafts">Drafts</Link> until you review and publish it.
          </p>
        </div>
        <div className="page-actions">
          {data && data.namespaces.length > 1 && (
            <select
              className="select hub-namespace"
              aria-label="Namespace"
              value={data.namespace}
              onChange={(e) => setAuthor(e.target.value)}
            >
              {data.namespaces.map((ns) => (
                <option key={ns} value={ns}>
                  {ns}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <Icon name="refresh" className={isFetching ? 'animate-spin' : undefined} />
            Refresh
          </button>
          <Link className="btn btn-primary" href="/generate">
            <Icon name="sparkles" />
            Generate
          </Link>
        </div>
      </div>

      {status === 503 && (
        <ConnectHuggingFace message={error instanceof Error ? error.message : undefined} />
      )}

      {error && status !== 503 && (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="alert" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">Couldn&apos;t list your datasets</div>
            <p className="card-desc">{error instanceof Error ? error.message : 'Unknown error'}</p>
          </div>
          <button type="button" className="btn btn-outline" onClick={() => refetch()}>
            <Icon name="refresh" />
            Try again
          </button>
        </div>
      )}

      {isPending && (
        <div className="hub-grid" aria-busy="true">
          {['a', 'b', 'c', 'd', 'e', 'f'].map((key) => (
            <div key={key} className="card hub-ds hub-skeleton" />
          ))}
        </div>
      )}

      {data && (
        <>
          <div className="stat-grid hub-stats">
            <StatTile icon="database" label="Datasets" value={formatCount(data.total)} />
            <StatTile icon="key" label="Private" value={formatCount(totals.private)} />
            <StatTile
              icon="download"
              label="Downloads, last 30 days"
              value={formatCount(totals.downloads)}
            />
            <StatTile icon="layers" label="Storage" value={formatBytes(totals.storage)} />
          </div>

          <div className="hub-toolbar">
            <label className="hub-search">
              <Icon name="search" />
              <input
                type="search"
                placeholder={`Search ${data.namespace}'s datasets`}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <fieldset className="tabs">
              <legend className="sr-only">Visibility</legend>
              {(['all', 'private', 'public'] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  className={cn('tab', visibility === v && 'active')}
                  aria-pressed={visibility === v}
                  onClick={() => setVisibility(v)}
                >
                  {v === 'all' ? 'All' : v === 'private' ? 'Private' : 'Public'}
                </button>
              ))}
            </fieldset>
            <select
              className="select hub-sort"
              aria-label="Sort by"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
            >
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {all.length === 0 ? (
            <div className="card hub-empty">
              <span className="cell-ic ic-lg">
                <Icon name="database" className="ic-lg" />
              </span>
              <div>
                <div className="card-title">No dataset in {data.namespace} yet</div>
                <p className="card-desc">
                  Generate one from a file, a web page or GitHub, review it in Drafts, then publish
                  it to Hugging Face: it shows up here.
                </p>
              </div>
              <Link className="btn btn-outline" href="/drafts">
                <Icon name="fileText" />
                Drafts
              </Link>
            </div>
          ) : shown.length === 0 ? (
            <p className="muted hub-none">No dataset matches these filters.</p>
          ) : (
            <div className={cn('hub-grid hub-results', isPlaceholderData && 'is-stale')}>
              {shown.map((dataset) => (
                <DatasetCard key={dataset.id} dataset={dataset} now={now} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
