'use client'

import Link from 'next/link'
import { type FormEvent, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { errorStatus } from '@/api/sdk'
import type { CollectionEvaluation, CollectionOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import {
  datasetHref,
  formatCount,
  formatDateTime,
  shortSha,
  splitRepoId,
  timeAgo,
} from '@/components/hub/format'
import {
  useCancelJobRun,
  useCollection,
  useCollections,
  useDeleteCollection,
  useEvaluateCollection,
  useHubDataset,
  useRebuildCollection,
  useSearchCollection,
} from '@/hooks'
import { rich, richLink } from '@/lib/rich'
import { cn } from '@/lib/utils'
import { BuildProgress, StatusBadge } from './collections-page'
import {
  type ComparisonCaveat,
  comparisonRows,
  DUPLICATE_SCORE,
  isEndpointModel,
  modelLabel,
  modelRemoved,
  percent,
  pythonSnippet,
  rowHref,
} from './format'

type Tab = 'search' | 'test' | 'use'

// The label of a tab is the `collection.tabs.<key>` message.
const TABS: { key: Tab; icon: string }[] = [
  { key: 'search', icon: 'search' },
  { key: 'test', icon: 'copyCheck' },
  { key: 'use', icon: 'terminal' },
]

function Header({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  const locale = useLocale()
  const tc = useTranslations('common')
  const router = useRouter()
  const rebuild = useRebuildCollection(collection.id)
  const remove = useDeleteCollection()
  const [confirming, setConfirming] = useState(false)
  const [now] = useState(() => Date.now())
  const building = collection.status === 'building'
  const atCommit = `${datasetHref(collection.repo_id)}?rev=${encodeURIComponent(collection.revision)}`

  const del = () =>
    remove.mutate(collection.id, {
      onSuccess: () => {
        toast.success(t('header.deleted', { name: collection.name }))
        router.push('/collections')
      },
      onError: (error) => toast.error(error.message),
    })

  return (
    <header className="hub-head">
      <div className="hub-head-main">
        <span className="cell-ic hub-head-ic">
          <Icon name="boxes" className="ic-lg" />
        </span>
        <div className="hub-head-text">
          <h1 className="page-title hub-title">
            {collection.name}
            <StatusBadge collection={collection} />
          </h1>
          <div className="hub-meta-line">
            <Link href={datasetHref(collection.repo_id)} className="mono">
              {collection.repo_id}
            </Link>
            <span>
              {collection.config === 'default' ? '' : `${collection.config} / `}
              {collection.split}
            </span>
            <Link href={atCommit} className="mono" title={collection.revision}>
              {shortSha(collection.revision)}
            </Link>
            <span title={collection.model}>{modelLabel(collection.model)}</span>
            {collection.points_count != null && (
              <span>
                {collection.rows_total != null && collection.rows_total !== collection.points_count
                  ? t('header.pointsOfRows', {
                      count: collection.points_count,
                      formatted: formatCount(collection.points_count, locale),
                      rows: collection.rows_total,
                      rowsFormatted: formatCount(collection.rows_total, locale),
                    })
                  : t('header.points', {
                      count: collection.points_count,
                      formatted: formatCount(collection.points_count, locale),
                    })}
              </span>
            )}
            {collection.vector_size != null && (
              <span>{t('header.dimensions', { count: collection.vector_size })}</span>
            )}
            {collection.built_at && (
              <span title={formatDateTime(collection.built_at, locale)}>
                {t('header.built', { time: timeAgo(collection.built_at, now, locale) })}
              </span>
            )}
          </div>
          <div className="hub-chips">
            <span className="tag">
              {t('header.embeds', { columns: collection.text_columns.join(' + ') })}
            </span>
            {collection.query_column && (
              <span className="tag">
                {t('header.asksWith', { column: collection.query_column })}
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="page-actions hub-head-actions">
        <button
          type="button"
          className="btn btn-outline"
          disabled={building || rebuild.isPending}
          onClick={() =>
            rebuild.mutate(null, {
              onSuccess: () => toast.success(t('header.rebuilding')),
              onError: (error) => toast.error(error.message),
            })
          }
        >
          <Icon name={rebuild.isPending ? 'loader' : 'refresh'} />
          {t('header.rebuild')}
        </button>
        {confirming ? (
          <span className="coll-confirm">
            <span className="hint">{t('header.confirmDelete')}</span>
            <button
              type="button"
              className="btn btn-destructive btn-sm"
              disabled={remove.isPending}
              onClick={del}
            >
              {tc('delete')}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setConfirming(false)}
            >
              {t('header.keep')}
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="btn btn-outline"
            disabled={building}
            title={building ? t('header.cancelFirst') : undefined}
            onClick={() => setConfirming(true)}
          >
            <Icon name="trash" />
            {tc('delete')}
          </button>
        )}
      </div>
    </header>
  )
}

function Building({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  const cancel = useCancelJobRun(collection.run_id ?? '')
  return (
    <div className="card coll-state">
      <div className="coll-state-text">
        <div className="card-title">{t('building.title')}</div>
        <p className="card-desc">
          {t('building.desc', { model: modelLabel(collection.model) })}{' '}
          {isEndpointModel(collection.model) ? t('building.endpoint') : t('building.local')}
          {collection.serving &&
            ` ${t('building.serving', { sha: shortSha(collection.revision) })}`}
        </p>
        <BuildProgress collection={collection} />
      </div>
      <button
        type="button"
        className="btn btn-outline"
        disabled={!collection.run_id || cancel.isPending}
        onClick={() => cancel.mutate(undefined, { onError: (error) => toast.error(error.message) })}
      >
        {cancel.isPending ? t('building.cancelling') : t('building.cancel')}
      </button>
    </div>
  )
}

function Failed({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  const rebuild = useRebuildCollection(collection.id)
  return (
    <div className="card hub-empty">
      <span className="cell-ic ic-lg">
        <Icon name="alert" className="ic-lg" />
      </span>
      <div>
        <div className="card-title">{t('failed.title')}</div>
        <p className="card-desc">
          {collection.error ?? t('failed.fallback')}
          {collection.serving && ` ${t('failed.serving', { sha: shortSha(collection.revision) })}`}
        </p>
      </div>
      <button
        type="button"
        className="btn btn-outline"
        disabled={rebuild.isPending}
        onClick={() =>
          rebuild.mutate(collection.revision, {
            onError: (error) => toast.error(error.message),
          })
        }
      >
        <Icon name="refresh" />
        {t('failed.buildAgain')}
      </button>
    </div>
  )
}

/** The dataset moved on since the build: say so, and offer the rebuild. */
function NewerCommit({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  const latest = useHubDataset(splitRepoId(collection.repo_id))
  const rebuild = useRebuildCollection(collection.id)
  const sha = latest.data?.sha
  if (!sha || sha === collection.revision || collection.status === 'building') return null
  return (
    <div className="hub-notice">
      <Icon name="clock" />
      <span>
        {t.rich('newerCommit.text', {
          latest: shortSha(sha),
          current: shortSha(collection.revision),
          mono: rich.mono,
        })}
      </span>
      <button
        type="button"
        className="btn btn-outline btn-sm"
        disabled={rebuild.isPending}
        onClick={() => rebuild.mutate(sha, { onError: (error) => toast.error(error.message) })}
      >
        {t('newerCommit.rebuildAt', { sha: shortSha(sha) })}
      </button>
    </div>
  )
}

/** The owner's endpoint is no longer the one that embedded the points: a
 * question would be embedded by another endpoint's model. */
function MovedEndpoint({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  const rebuild = useRebuildCollection(collection.id)
  if (!collection.current_endpoint || collection.status !== 'ready') return null
  return (
    <div className="hub-notice coll-warn-box">
      <Icon name="alert" />
      <span>
        {t.rich('movedEndpoint.text', {
          endpoint: collection.endpoint ?? '',
          current: collection.current_endpoint,
          mono: rich.mono,
        })}
      </span>
      <button
        type="button"
        className="btn btn-outline btn-sm"
        disabled={rebuild.isPending}
        onClick={() =>
          rebuild.mutate(collection.revision, { onError: (error) => toast.error(error.message) })
        }
      >
        {t('movedEndpoint.buildAgain')}
      </button>
    </div>
  )
}

/** Built with a local model, which the server no longer runs: nothing can
 * search, test or rebuild it as it is. */
function RemovedModel({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  return (
    <div className="card coll-state">
      <div className="coll-state-text">
        <div className="card-title">{t('removedModel.title')}</div>
        <p className="card-desc">
          {t.rich('removedModel.text', {
            model: modelLabel(collection.model),
            mono: rich.mono,
            link: richLink(datasetHref(collection.repo_id)),
          })}
        </p>
      </div>
    </div>
  )
}

/** A cosine as a thin bar: one magnitude, one hue (the viewer's chart color). */
function ScoreMeter({ score }: { score: number }) {
  const t = useTranslations('collection')
  const width = Math.max(0, Math.min(1, score)) * 100
  return (
    <span className="coll-meter" title={t('score', { score: score.toFixed(3) })}>
      <span className="coll-meter-track">
        <span style={{ width: `${width}%` }} />
      </span>
      <span className="mono">{score.toFixed(3)}</span>
    </span>
  )
}

function SearchPanel({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  const locale = useLocale()
  const tc = useTranslations('common')
  const search = useSearchCollection(collection.id)
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(10)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (query.trim()) search.mutate({ query: query.trim(), limit })
  }

  const found = search.data
  return (
    <div className="coll-panel">
      <form className="hub-toolbar" onSubmit={submit}>
        <input
          className="input hub-search"
          placeholder={t('search.placeholder')}
          aria-label={t('search.queryLabel')}
          maxLength={2000}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="select"
          aria-label={t('search.resultsLabel')}
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
        >
          {[5, 10, 20, 50].map((n) => (
            <option key={n} value={n}>
              {t('top', { count: n })}
            </option>
          ))}
        </select>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!query.trim() || search.isPending}
        >
          <Icon name={search.isPending ? 'loader' : 'search'} />
          {tc('search')}
        </button>
      </form>

      {search.error && <div className="hint coll-error">{search.error.message}</div>}

      {found && (
        <>
          <p className="hint">
            {t('search.summary', {
              count: found.hits.length,
              query: found.query,
              ms: found.took_ms,
              model: modelLabel(collection.model),
            })}
          </p>
          {found.hits.length === 0 ? (
            <div className="card hub-empty">
              <p className="card-desc">{t('search.empty')}</p>
            </div>
          ) : (
            <ol className="coll-hits">
              {found.hits.map((hit, i) => (
                <li key={hit.row_idx} className="card coll-hit">
                  <div className="coll-hit-head">
                    <span className="coll-rank">#{i + 1}</span>
                    <ScoreMeter score={hit.score} />
                    <Link href={rowHref(collection, hit.row_idx)} className="hint">
                      {t('row', { index: formatCount(hit.row_idx, locale) })}
                    </Link>
                  </div>
                  <p className="coll-hit-text">{hit.text}</p>
                  <Fields fields={hit.fields} skip={collection.text_columns} />
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  )
}

/** The payload columns that aren't already the embedded text. */
function Fields({ fields, skip }: { fields: Record<string, unknown>; skip: string[] }) {
  const shown = Object.entries(fields).filter(
    ([name, value]) => !skip.includes(name) && value !== '' && value != null,
  )
  if (!shown.length) return null
  return (
    <dl className="coll-fields">
      {shown.map(([name, value]) => (
        <div key={name}>
          <dt className="mono">{name}</dt>
          <dd>{String(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function Metrics({ result }: { result: CollectionEvaluation }) {
  const t = useTranslations('collection')
  const locale = useLocale()
  return (
    <div className="stat-grid hub-stats">
      <div className="card stat">
        <div className="stat-label">{t('metrics.foundFirst')}</div>
        <div className="stat-val">{percent(result.hit_at_1, locale)}</div>
        <div className="stat-delta">{t('metrics.foundFirstHint')}</div>
      </div>
      <div className="card stat">
        <div className="stat-label">{t('metrics.inTopK', { k: result.k })}</div>
        <div className="stat-val">{percent(result.hit_at_k, locale)}</div>
        <div className="stat-delta">{t('metrics.inTopKHint')}</div>
      </div>
      <div className="card stat">
        <div className="stat-label">{t('metrics.mrr')}</div>
        <div className="stat-val">{result.mrr.toFixed(2)}</div>
        <div className="stat-delta">{t('metrics.mrrHint', { k: result.k })}</div>
      </div>
      <div className="card stat">
        <div className="stat-label">{t('metrics.rowsTested')}</div>
        <div className="stat-val">{formatCount(result.queries, locale)}</div>
        <div className="stat-delta">
          {t('metrics.rowsTestedHint', { column: result.query_column })}
        </div>
      </div>
    </div>
  )
}

function TestPanel({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  const locale = useLocale()
  const evaluate = useEvaluateCollection(collection.id)
  const result = evaluate.data ?? collection.evaluation ?? null
  const [column, setColumn] = useState(collection.query_column ?? '')
  const [sample, setSample] = useState(100)
  const [k, setK] = useState(10)
  const [now] = useState(() => Date.now())

  const run = (event: FormEvent) => {
    event.preventDefault()
    evaluate.mutate(
      { query_column: column || null, sample, k },
      { onError: (error) => toast.error(error.message) },
    )
  }

  return (
    <div className="coll-panel">
      <p className="hint coll-lead">{t('test.lead')}</p>
      <form className="hub-toolbar" onSubmit={run}>
        <label className="label" htmlFor="coll-test-column">
          {t('test.askWith')}
        </label>
        <select
          id="coll-test-column"
          className="select mono"
          value={column}
          onChange={(e) => setColumn(e.target.value)}
        >
          {!collection.query_column && <option value="">{t('test.pickColumn')}</option>}
          {(collection.fields ?? []).map((field) => (
            <option key={field} value={field}>
              {field}
            </option>
          ))}
        </select>
        <select
          className="select"
          aria-label={t('test.sampleLabel')}
          value={sample}
          onChange={(e) => setSample(Number(e.target.value))}
        >
          {[50, 100, 200, 500].map((n) => (
            <option key={n} value={n}>
              {t('test.sampleOption', { count: n })}
            </option>
          ))}
        </select>
        <select
          className="select"
          aria-label={t('test.topKLabel')}
          value={k}
          onChange={(e) => setK(Number(e.target.value))}
        >
          {[1, 5, 10, 20, 50].map((n) => (
            <option key={n} value={n}>
              {t('top', { count: n })}
            </option>
          ))}
        </select>
        <button type="submit" className="btn btn-primary" disabled={!column || evaluate.isPending}>
          <Icon name={evaluate.isPending ? 'loader' : 'play'} />
          {t('test.run')}
        </button>
      </form>

      {!result && !evaluate.isPending && (
        <div className="card hub-empty">
          <p className="card-desc">{t('test.notTested')}</p>
        </div>
      )}

      {result && (
        <>
          {result.trivial && (
            <div className="hub-notice coll-warn-box">
              <Icon name="alert" />
              <span>
                {t.rich('test.trivial', { column: result.query_column, mono: rich.mono })}
              </span>
            </div>
          )}
          <Metrics result={result} />
          <p className="hint">
            {t('test.tested', {
              time: timeAgo(result.evaluated_at, now, locale),
              queries: formatCount(result.queries, locale),
              sample: formatCount(result.sample, locale),
              k: result.k,
            })}
          </p>
          {result.misses.length > 0 ? (
            <Misses collection={collection} result={result} />
          ) : (
            <p className="hint">{t('test.allFound')}</p>
          )}
        </>
      )}
      <Comparison collection={{ ...collection, evaluation: result }} />
    </div>
  )
}

/** Why a compared collection's figures can't be read next to this one's. */
function CaveatText({ caveat }: { caveat: ComparisonCaveat }) {
  const t = useTranslations('collection')
  switch (caveat.key) {
    case 'trivial':
      return t('compare.caveat.trivial', { column: caveat.column })
    case 'askedWith':
      return t('compare.caveat.askedWith', { column: caveat.column })
    case 'sampled':
      return t('compare.caveat.sampled', { sample: caveat.sample })
    case 'topK':
      return t('compare.caveat.topK', { k: caveat.k })
    default:
      return t(`compare.caveat.${caveat.key}`)
  }
}

/** The collections of the same split at the same commit, their latest tests
 * side by side: which model and which columns find the rows best. */
function Comparison({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  const locale = useLocale()
  const all = useCollections()
  const rows = comparisonRows(collection, all.data?.collections ?? [])
  if (rows.length === 0) return null
  return (
    <div className="card coll-compare">
      <div className="card-head">
        <div>
          <div className="card-title">{t('compare.title')}</div>
          <p className="card-desc">{t('compare.desc')}</p>
        </div>
      </div>
      <div className="coll-table-wrap">
        <table className="table stack-table">
          <thead>
            <tr>
              <th>{t('compare.collection')}</th>
              <th>{t('compare.model')}</th>
              <th>{t('compare.embeds')}</th>
              <th className="coll-num">{t('compare.foundFirst')}</th>
              <th className="coll-num">{t('compare.inTopK')}</th>
              <th className="coll-num">{t('compare.mrr')}</th>
              <th className="coll-num">{t('compare.rows')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ collection: other, current, caveat }) => {
              const test = other.evaluation
              return (
                <tr key={other.id} className={cn(current && 'coll-compare-current')}>
                  <td data-label={t('compare.collection')}>
                    {current ? (
                      <span>
                        {other.name} <span className="badge">{t('compare.thisOne')}</span>
                      </span>
                    ) : (
                      <Link href={`/collections/${other.id}`}>{other.name}</Link>
                    )}
                    {caveat && (
                      <div className="hint coll-cell-text">
                        <CaveatText caveat={caveat} />
                      </div>
                    )}
                  </td>
                  <td className="mono" data-label={t('compare.model')}>
                    {modelLabel(other.model)}
                  </td>
                  <td className="mono" data-label={t('compare.embeds')}>
                    {other.text_columns.join(', ')}
                  </td>
                  <td className="coll-num mono" data-label={t('compare.foundFirst')}>
                    {test ? percent(test.hit_at_1, locale) : '—'}
                  </td>
                  <td className="coll-num mono" data-label={t('compare.inTopK')}>
                    {test ? percent(test.hit_at_k, locale) : '—'}
                  </td>
                  <td className="coll-num mono" data-label={t('compare.mrr')}>
                    {test ? test.mrr.toFixed(2) : '—'}
                  </td>
                  <td className="coll-num mono" data-label={t('compare.rows')}>
                    {test ? formatCount(test.queries, locale) : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Misses({
  collection,
  result,
}: {
  collection: CollectionOut
  result: CollectionEvaluation
}) {
  const t = useTranslations('collection')
  const locale = useLocale()
  return (
    <div className="card coll-misses">
      <div className="card-head">
        <div>
          <div className="card-title">{t('misses.title')}</div>
          <p className="card-desc">
            {result.misses.length === 20
              ? t('misses.descFirst', { count: result.misses.length })
              : t('misses.desc')}
          </p>
        </div>
      </div>
      <div className="coll-table-wrap">
        <table className="table stack-table">
          <thead>
            <tr>
              <th>{t('misses.asked')}</th>
              <th>{t('misses.ownRow')}</th>
              <th>{t('misses.cameFirst')}</th>
              <th className="coll-num">{t('misses.rank')}</th>
            </tr>
          </thead>
          <tbody>
            {result.misses.map((miss) => (
              <tr key={miss.row_idx}>
                <td data-label={t('misses.asked')}>{miss.query}</td>
                <td data-label={t('misses.ownRow')}>
                  <Link href={rowHref(collection, miss.row_idx)} className="hint">
                    {t('row', { index: formatCount(miss.row_idx, locale) })}
                  </Link>
                  <div className="coll-cell-text">{miss.expected}</div>
                </td>
                <td data-label={t('misses.cameFirst')}>
                  {miss.top_row_idx != null ? (
                    <>
                      <span className="coll-top-head">
                        <Link href={rowHref(collection, miss.top_row_idx)} className="hint">
                          {t('row', { index: formatCount(miss.top_row_idx, locale) })}
                        </Link>
                        {miss.top_score != null && <ScoreMeter score={miss.top_score} />}
                        {miss.top_score != null && miss.top_score >= DUPLICATE_SCORE && (
                          <span className="badge badge-warning">{t('misses.duplicate')}</span>
                        )}
                      </span>
                      <div className="coll-cell-text">{miss.top_text}</div>
                    </>
                  ) : (
                    <span className="hint">{t('misses.nothing')}</span>
                  )}
                </td>
                <td className="coll-num mono" data-label={t('misses.rank')}>
                  {miss.rank ?? `>${result.k}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function UsePanel({ collection }: { collection: CollectionOut }) {
  const t = useTranslations('collection')
  const tc = useTranslations('common')
  const snippet = pythonSnippet(collection)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(snippet)
      toast.success(tc('copied'))
    } catch {
      toast.error(t('use.copyFailed'))
    }
  }
  return (
    <div className="coll-panel">
      <p className="hint coll-lead">{t.rich('use.lead', { mono: rich.mono })}</p>
      <div className="card coll-snippet">
        <div className="coll-snippet-head">
          <span className="mono">{collection.qdrant_collection}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={copy}>
            <Icon name="copy" />
            {tc('copy')}
          </button>
        </div>
        <pre className="mono">{snippet}</pre>
      </div>
    </div>
  )
}

export function CollectionPage({ id }: { id: string }) {
  const t = useTranslations('collection')
  const collection = useCollection(id)
  const [tab, setTab] = useState<Tab>('search')
  const status = errorStatus(collection.error)

  const back = (
    <Link href="/collections" className="btn btn-ghost btn-sm hub-back">
      <Icon name="chevronLeft" />
      {t('back')}
    </Link>
  )

  if (collection.isPending) {
    return (
      <div className="hub-page coll-page">
        {back}
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          {t('loading')}
        </div>
      </div>
    )
  }

  if (collection.error) {
    return (
      <div className="hub-page coll-page">
        {back}
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="alert" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">{status === 404 ? t('notFound') : t('loadFailed')}</div>
            <p className="card-desc">{collection.error.message}</p>
          </div>
          {status !== 404 && (
            <button type="button" className="btn btn-outline" onClick={() => collection.refetch()}>
              <Icon name="refresh" />
              {t('tryAgain')}
            </button>
          )}
        </div>
      </div>
    )
  }

  const c = collection.data
  return (
    <div className="hub-page coll-page">
      {back}
      <Header collection={c} />
      {c.status === 'building' && <Building collection={c} />}
      {c.status === 'failed' && <Failed collection={c} />}
      {!modelRemoved(c) && <NewerCommit collection={c} />}
      <MovedEndpoint collection={c} />
      {modelRemoved(c) && c.status !== 'building' && <RemovedModel collection={c} />}

      {(c.status === 'ready' || c.serving) && !modelRemoved(c) && (
        <>
          <nav className="tabs hub-tabs" aria-label={t('sections')}>
            {TABS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={cn('tab', tab === item.key && 'active')}
                aria-current={tab === item.key ? 'page' : undefined}
                onClick={() => setTab(item.key)}
              >
                <Icon name={item.icon} />
                {t(`tabs.${item.key}`)}
              </button>
            ))}
          </nav>
          {tab === 'search' && <SearchPanel collection={c} />}
          {tab === 'test' && <TestPanel collection={c} />}
          {tab === 'use' && <UsePanel collection={c} />}
        </>
      )}
    </div>
  )
}
