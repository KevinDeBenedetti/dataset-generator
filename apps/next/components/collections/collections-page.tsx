'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useRouter, useSearchParams } from 'next/navigation'
import type { CollectionOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatCount, shortSha, timeAgo } from '@/components/hub/format'
import { useCollections } from '@/hooks'
import { rich, richLink } from '@/lib/rich'
import { CreateCollectionForm } from './create-form'
import { endpointMoved, modelLabel, modelRemoved, percent } from './format'

// A tag renderer for `t.rich(...)`, defined at module level so it is stable.
const datasetsLink = richLink('/datasets')

export function StatusBadge({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collections')
  if (collection.status !== 'building' && modelRemoved(collection)) {
    return (
      <span className="badge badge-warning" title={t('status.modelRemovedTitle')}>
        <Icon name="alert" className="ic-sm" />
        {t('status.modelRemoved')}
      </span>
    )
  }
  if (endpointMoved(collection)) {
    return (
      <span
        className="badge badge-warning"
        title={t('status.rebuildNeededTitle', {
          endpoint: String(collection.endpoint),
          current: String(collection.current_endpoint),
        })}
      >
        <Icon name="alert" className="ic-sm" />
        {t('status.rebuildNeeded')}
      </span>
    )
  }
  if (collection.status === 'ready') {
    return (
      <span className="badge badge-success">
        <Icon name="check" className="ic-sm" />
        {t('status.ready')}
      </span>
    )
  }
  if (collection.status === 'failed') {
    return (
      <span className="badge badge-destructive">
        <Icon name="alert" className="ic-sm" />
        {t('status.failed')}
      </span>
    )
  }
  return (
    <span className="badge badge-info">
      <Icon name="loader" className="ic-sm animate-spin" />
      {t('status.building')}
    </span>
  )
}

/** The build's progress bar and step, while a worker embeds the split. */
export function BuildProgress({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collections')
  const locale = useLocale()
  const { done = 0, total = 0, label = '' } = collection.progress ?? {}
  const share = total > 0 ? done / total : 0
  return (
    <div className="coll-progress">
      {/* The step below says it in words; the bar only draws it. */}
      <div className="progress" aria-hidden="true">
        <span style={{ width: `${Math.max(4, share * 100)}%` }} />
      </div>
      <span className="hint" aria-live="polite">
        {total > 0
          ? [
              label || t('progress.embedding'),
              `${formatCount(done, locale)} / ${formatCount(total, locale)}`,
            ].join(' · ')
          : label || t('progress.waiting')}
      </span>
    </div>
  )
}

function CollectionRow({ collection, now }: { collection: CollectionOut; now: number }) {
  const t = useTranslations('collections')
  const locale = useLocale()
  const test = collection.evaluation
  return (
    <li className="coll-item">
      <Link href={`/collections/${collection.id}`} className="coll-item-link">
        <span className="cell-ic">
          <Icon name="boxes" />
        </span>
        <span className="coll-item-main">
          <span className="coll-item-title">
            {collection.name}
            <StatusBadge collection={collection} />
          </span>
          <span className="coll-item-meta">
            <span className="mono">{collection.repo_id}</span>
            <span>
              {collection.config === 'default' ? '' : `${collection.config} / `}
              {collection.split}
            </span>
            <span className="mono" title={collection.revision}>
              {shortSha(collection.revision)}
            </span>
            <span>{modelLabel(collection.model)}</span>
            <span>{t('row.updated', { time: timeAgo(collection.updated_at, now, locale) })}</span>
          </span>
          {collection.status === 'building' && <BuildProgress collection={collection} />}
          {collection.status === 'failed' && collection.error && (
            <span className="hint coll-error">{collection.error}</span>
          )}
        </span>
        <span className="coll-item-stats">
          {collection.points_count != null && collection.status === 'ready' && (
            <span>
              {t.rich('row.points', {
                count: collection.points_count,
                formatted: formatCount(collection.points_count, locale),
                b: rich.b,
              })}
            </span>
          )}
          {test && collection.status === 'ready' && (
            <span title={t('row.testTitle', { queries: test.queries, k: test.k })}>
              {t.rich('row.foundFirst', { percent: percent(test.hit_at_1, locale), b: rich.b })}
            </span>
          )}
        </span>
        <Icon name="chevronRight" className="coll-item-go" />
      </Link>
    </li>
  )
}

export function CollectionsPage() {
  const t = useTranslations('collections')
  const router = useRouter()
  const params = useSearchParams()
  const initialRepo = params.get('repo')
  const textParam = params.get('text')
  const initialColumns = textParam
    ? { text: textParam.split(',').filter(Boolean), query: params.get('query') }
    : null
  const collections = useCollections()
  const [creating, setCreating] = useState(Boolean(initialRepo))
  const [now] = useState(() => Date.now())

  const data = collections.data
  const list = data?.collections ?? []
  const full = Boolean(data && data.quota > 0 && list.length >= data.quota)

  const closeForm = () => {
    setCreating(false)
    if (initialRepo) router.replace('/collections')
  }

  return (
    <div className="hub-page coll-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">{t('title')}</h1>
          <p className="page-sub">{t('subtitle')}</p>
        </div>
        {data?.qdrant_configured && !creating && (
          <div className="page-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setCreating(true)}
              disabled={full}
              title={full ? t('quotaReached', { quota: data.quota }) : undefined}
            >
              <Icon name="plus" />
              {t('new')}
            </button>
          </div>
        )}
      </div>

      {collections.isPending && (
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          {t('loading')}
        </div>
      )}

      {collections.error && (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="alert" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">{t('loadFailed')}</div>
            <p className="card-desc">{collections.error.message}</p>
          </div>
          <button type="button" className="btn btn-outline" onClick={() => collections.refetch()}>
            <Icon name="refresh" />
            {t('tryAgain')}
          </button>
        </div>
      )}

      {data && !data.qdrant_configured && (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="boxes" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">{t('noQdrant.title')}</div>
            <p className="card-desc">{t.rich('noQdrant.description', { code: rich.code })}</p>
          </div>
        </div>
      )}

      {data?.qdrant_configured && creating && (
        <CreateCollectionForm
          models={data.models}
          initialRepo={initialRepo}
          initialColumns={initialColumns}
          onCancel={closeForm}
        />
      )}

      {data && list.length === 0 && data.qdrant_configured && !creating && (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="boxes" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">{t('empty.title')}</div>
            <p className="card-desc">{t.rich('empty.description', { b: rich.b })}</p>
          </div>
          <button type="button" className="btn btn-outline" onClick={() => setCreating(true)}>
            <Icon name="plus" />
            {t('new')}
          </button>
        </div>
      )}

      {list.length > 0 && (
        <ul className="card coll-list">
          {list.map((c) => (
            <CollectionRow key={c.id} collection={c} now={now} />
          ))}
        </ul>
      )}

      {list.length > 0 && (
        <p className="hint coll-foot">
          {t.rich('footer', { link: datasetsLink })}{' '}
          {data && data.quota > 0 && t('quota', { count: list.length, quota: data.quota })}
        </p>
      )}
    </div>
  )
}
