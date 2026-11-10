'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import type { CollectionOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatCount, shortSha, timeAgo } from '@/components/hub/format'
import { useCollections } from '@/hooks'
import { CreateCollectionForm } from './create-form'
import { modelLabel, percent } from './format'

export function StatusBadge({ collection }: { collection: CollectionOut }) {
  if (collection.status === 'ready') {
    return (
      <span className="badge badge-success">
        <Icon name="check" className="ic-sm" />
        Ready
      </span>
    )
  }
  if (collection.status === 'failed') {
    return (
      <span className="badge badge-destructive">
        <Icon name="alert" className="ic-sm" />
        Failed
      </span>
    )
  }
  return (
    <span className="badge badge-info">
      <Icon name="loader" className="ic-sm animate-spin" />
      Building
    </span>
  )
}

/** The build's progress bar and step, while a worker embeds the split. */
export function BuildProgress({ collection }: { collection: CollectionOut }) {
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
          ? `${label || 'Embedding rows'} · ${formatCount(done)} / ${formatCount(total)}`
          : label || 'Waiting for a worker…'}
      </span>
    </div>
  )
}

function CollectionRow({ collection, now }: { collection: CollectionOut; now: number }) {
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
            <span>Updated {timeAgo(collection.updated_at, now)}</span>
          </span>
          {collection.status === 'building' && <BuildProgress collection={collection} />}
          {collection.status === 'failed' && collection.error && (
            <span className="hint coll-error">{collection.error}</span>
          )}
        </span>
        <span className="coll-item-stats">
          {collection.points_count != null && collection.status === 'ready' && (
            <span>
              <b>{formatCount(collection.points_count)}</b> points
            </span>
          )}
          {test && collection.status === 'ready' && (
            <span title={`Retrieval test on ${test.queries} rows, k = ${test.k}`}>
              <b>{percent(test.hit_at_1)}</b> found first
            </span>
          )}
        </span>
        <Icon name="chevronRight" className="coll-item-go" />
      </Link>
    </li>
  )
}

export function CollectionsPage() {
  const router = useRouter()
  const params = useSearchParams()
  const initialRepo = params.get('repo')
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
          <h1 className="page-title">Collections</h1>
          <p className="page-sub">
            Splits of your Hugging Face datasets, embedded into Qdrant with your endpoint&apos;s
            embedding model. Build one, then search it and test how well its questions find their
            answers.
          </p>
        </div>
        {data?.qdrant_configured && !creating && (
          <div className="page-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setCreating(true)}
              disabled={full}
              title={full ? `You have ${data.quota} collections, the limit` : undefined}
            >
              <Icon name="plus" />
              New collection
            </button>
          </div>
        )}
      </div>

      {collections.isPending && (
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          Loading your collections…
        </div>
      )}

      {collections.error && (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="alert" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">Couldn&apos;t load your collections</div>
            <p className="card-desc">{collections.error.message}</p>
          </div>
          <button type="button" className="btn btn-outline" onClick={() => collections.refetch()}>
            <Icon name="refresh" />
            Try again
          </button>
        </div>
      )}

      {data && !data.qdrant_configured && (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="boxes" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">Qdrant is not set up</div>
            <p className="card-desc">
              Collections are stored in Qdrant. The local stack runs one (<code>make dev</code>);
              elsewhere, set <code>QDRANT_URL</code> (and <code>QDRANT_API_KEY</code> when it needs
              one) on the server and its worker.
            </p>
          </div>
        </div>
      )}

      {data?.qdrant_configured && creating && (
        <CreateCollectionForm models={data.models} initialRepo={initialRepo} onCancel={closeForm} />
      )}

      {data && list.length === 0 && data.qdrant_configured && !creating && (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="boxes" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">No collection yet</div>
            <p className="card-desc">
              Pick a dataset and a split: a worker embeds every row, then you can search it, test
              it, and query it from your own code. Start from a dataset&apos;s page with{' '}
              <b>Build a collection</b>, or here.
            </p>
          </div>
          <button type="button" className="btn btn-outline" onClick={() => setCreating(true)}>
            <Icon name="plus" />
            New collection
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
          A collection reads its dataset at one commit: <Link href="/datasets">publish</Link> new
          pairs, then rebuild it from its page.{' '}
          {data && data.quota > 0 && `${list.length} of ${data.quota} collections.`}
        </p>
      )}
    </div>
  )
}
