'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { errorStatus } from '@/api/sdk'
import type { HuggingFaceDataset } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { useHubDatasets } from '@/hooks'
import { cn } from '@/lib/utils'
import { datasetHref, formatBytes, formatCount, splitRepoId, timeAgo } from './format'
import { richLink } from '@/lib/rich'

type Visibility = 'all' | 'private' | 'public'
type SortKey = 'updated' | 'name' | 'downloads' | 'likes' | 'size'

// The option labels are the `datasets.list.sorts.<key>` messages.
const SORTS: SortKey[] = ['updated', 'name', 'downloads', 'likes', 'size']

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
  const t = useTranslations('datasets')
  const locale = useLocale()
  const tags = (dataset.tags ?? []).filter(
    (tag) => !NOISE_TAG.test(tag) && !tag.startsWith('language:'),
  )
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
            {t('private')}
          </span>
        ) : (
          <span className="badge badge-outline">
            <Icon name="globe" className="ic-sm" />
            {t('public')}
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
          {timeAgo(dataset.last_modified, now, locale)}
        </span>
        {dataset.used_storage != null && (
          <span>
            <Icon name="layers" className="ic-sm" />
            {formatBytes(dataset.used_storage, locale)}
          </span>
        )}
        {dataset.size_category && <span className="mono">{dataset.size_category}</span>}
        <span title={t('list.downloadsTitle')}>
          <Icon name="download" className="ic-sm" />
          {formatCount(dataset.downloads ?? 0, locale)}
        </span>
        <span title={t('list.likesTitle')}>
          <Icon name="star" className="ic-sm" />
          {formatCount(dataset.likes ?? 0, locale)}
        </span>
      </div>
    </Link>
  )
}

/** Shown when the API answers 503: no Hugging Face token yet. */
export function ConnectHuggingFace({ message }: { message?: string }) {
  const t = useTranslations('datasets')
  return (
    <div className="card hub-empty">
      <span className="cell-ic ic-lg">
        <Icon name="key" className="ic-lg" />
      </span>
      <div>
        <div className="card-title">{t('connect.title')}</div>
        <p className="card-desc">
          {t('connect.description')} {message}
        </p>
      </div>
      <Link className="btn btn-primary" href="/settings">
        <Icon name="settings" />
        {t('connect.openSettings')}
      </Link>
    </div>
  )
}

export function HubDatasetsList() {
  const t = useTranslations('datasets')
  const tc = useTranslations('common')
  const locale = useLocale()
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
          <h1 className="page-title">{t('title')}</h1>
          <p className="page-sub">
            {t.rich('list.subtitle', {
              drafts: richLink('/drafts'),
            })}
          </p>
        </div>
        <div className="page-actions">
          {data && data.namespaces.length > 1 && (
            <select
              className="select hub-namespace"
              aria-label={t('list.namespace')}
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
            {tc('refresh')}
          </button>
          <Link className="btn btn-primary" href="/generate">
            <Icon name="sparkles" />
            {t('list.generate')}
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
            <div className="card-title">{t('list.loadFailed')}</div>
            <p className="card-desc">
              {error instanceof Error ? error.message : tc('unknownError')}
            </p>
          </div>
          <button type="button" className="btn btn-outline" onClick={() => refetch()}>
            <Icon name="refresh" />
            {t('tryAgain')}
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
            <StatTile
              icon="database"
              label={t('list.stats.datasets')}
              value={formatCount(data.total, locale)}
            />
            <StatTile
              icon="key"
              label={t('list.stats.private')}
              value={formatCount(totals.private, locale)}
            />
            <StatTile
              icon="download"
              label={t('list.stats.downloads')}
              value={formatCount(totals.downloads, locale)}
            />
            <StatTile
              icon="layers"
              label={t('list.stats.storage')}
              value={formatBytes(totals.storage, locale)}
            />
          </div>

          <div className="hub-toolbar">
            <label className="hub-search">
              <Icon name="search" />
              <input
                type="search"
                placeholder={t('list.searchPlaceholder', { namespace: data.namespace })}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <fieldset className="tabs">
              <legend className="sr-only">{t('list.visibility')}</legend>
              {(['all', 'private', 'public'] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  className={cn('tab', visibility === v && 'active')}
                  aria-pressed={visibility === v}
                  onClick={() => setVisibility(v)}
                >
                  {v === 'all' ? tc('all') : t(v)}
                </button>
              ))}
            </fieldset>
            <select
              className="select hub-sort"
              aria-label={t('list.sortBy')}
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
            >
              {SORTS.map((key) => (
                <option key={key} value={key}>
                  {t(`list.sorts.${key}`)}
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
                <div className="card-title">
                  {t('list.emptyTitle', { namespace: data.namespace })}
                </div>
                <p className="card-desc">{t('list.emptyDescription')}</p>
              </div>
              <Link className="btn btn-outline" href="/drafts">
                <Icon name="fileText" />
                {t('list.drafts')}
              </Link>
            </div>
          ) : shown.length === 0 ? (
            <p className="muted hub-none">{t('list.noMatch')}</p>
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
