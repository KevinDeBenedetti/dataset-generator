'use client'

import Link from 'next/link'
import { type FormEvent, useState } from 'react'
import { useRouter } from 'next/navigation'
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
  useDeleteCollection,
  useEvaluateCollection,
  useHubDataset,
  useRebuildCollection,
  useSearchCollection,
} from '@/hooks'
import { cn } from '@/lib/utils'
import { BuildProgress, StatusBadge } from './collections-page'
import {
  DUPLICATE_SCORE,
  isEndpointModel,
  modelLabel,
  percent,
  pythonSnippet,
  rowHref,
} from './format'

type Tab = 'search' | 'test' | 'use'

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'search', label: 'Search', icon: 'search' },
  { key: 'test', label: 'Retrieval test', icon: 'copyCheck' },
  { key: 'use', label: 'Use it', icon: 'terminal' },
]

function Header({ collection }: { collection: CollectionOut }) {
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
        toast.success(`Deleted "${collection.name}"`)
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
                {formatCount(collection.points_count)} points
                {collection.rows_total != null && collection.rows_total !== collection.points_count
                  ? ` of ${formatCount(collection.rows_total)} rows`
                  : ''}
              </span>
            )}
            {collection.vector_size != null && <span>{collection.vector_size} dimensions</span>}
            {collection.built_at && (
              <span title={formatDateTime(collection.built_at)}>
                Built {timeAgo(collection.built_at, now)}
              </span>
            )}
          </div>
          <div className="hub-chips">
            <span className="tag">embeds: {collection.text_columns.join(' + ')}</span>
            {collection.query_column && (
              <span className="tag">asks with: {collection.query_column}</span>
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
              onSuccess: () => toast.success('Rebuilding at the latest commit'),
              onError: (error) => toast.error(error.message),
            })
          }
        >
          <Icon name={rebuild.isPending ? 'loader' : 'refresh'} />
          Rebuild
        </button>
        {confirming ? (
          <span className="coll-confirm">
            <span className="hint">Delete it and its vectors?</span>
            <button
              type="button"
              className="btn btn-destructive btn-sm"
              disabled={remove.isPending}
              onClick={del}
            >
              Delete
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setConfirming(false)}
            >
              Keep
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="btn btn-outline"
            disabled={building}
            title={building ? 'Cancel the build first' : undefined}
            onClick={() => setConfirming(true)}
          >
            <Icon name="trash" />
            Delete
          </button>
        )}
      </div>
    </header>
  )
}

function Building({ collection }: { collection: CollectionOut }) {
  const cancel = useCancelJobRun(collection.run_id ?? '')
  return (
    <div className="card coll-state">
      <div className="coll-state-text">
        <div className="card-title">Embedding the split</div>
        <p className="card-desc">
          A worker reads the split from Hugging Face, embeds every row with{' '}
          {modelLabel(collection.model)} and stores the vectors in Qdrant.{' '}
          {isEndpointModel(collection.model)
            ? 'The rows are sent to your endpoint to be embedded.'
            : 'The first build with a model downloads it too.'}
        </p>
        <BuildProgress collection={collection} />
      </div>
      <button
        type="button"
        className="btn btn-outline"
        disabled={!collection.run_id || cancel.isPending}
        onClick={() => cancel.mutate(undefined, { onError: (error) => toast.error(error.message) })}
      >
        {cancel.isPending ? 'Cancelling…' : 'Cancel the build'}
      </button>
    </div>
  )
}

function Failed({ collection }: { collection: CollectionOut }) {
  const rebuild = useRebuildCollection(collection.id)
  return (
    <div className="card hub-empty">
      <span className="cell-ic ic-lg">
        <Icon name="alert" className="ic-lg" />
      </span>
      <div>
        <div className="card-title">The build didn&apos;t finish</div>
        <p className="card-desc">{collection.error ?? 'The build failed.'}</p>
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
        Build again
      </button>
    </div>
  )
}

/** The dataset moved on since the build: say so, and offer the rebuild. */
function NewerCommit({ collection }: { collection: CollectionOut }) {
  const latest = useHubDataset(splitRepoId(collection.repo_id))
  const rebuild = useRebuildCollection(collection.id)
  const sha = latest.data?.sha
  if (!sha || sha === collection.revision || collection.status === 'building') return null
  return (
    <div className="hub-notice">
      <Icon name="clock" />
      <span>
        The dataset has a newer commit, <span className="mono">{shortSha(sha)}</span>: this
        collection still holds <span className="mono">{shortSha(collection.revision)}</span>.
      </span>
      <button
        type="button"
        className="btn btn-outline btn-sm"
        disabled={rebuild.isPending}
        onClick={() => rebuild.mutate(sha, { onError: (error) => toast.error(error.message) })}
      >
        Rebuild at {shortSha(sha)}
      </button>
    </div>
  )
}

/** A cosine as a thin bar: one magnitude, one hue (the viewer's chart color). */
function ScoreMeter({ score }: { score: number }) {
  const width = Math.max(0, Math.min(1, score)) * 100
  return (
    <span className="coll-meter" title={`Cosine similarity ${score.toFixed(3)}`}>
      <span className="coll-meter-track">
        <span style={{ width: `${width}%` }} />
      </span>
      <span className="mono">{score.toFixed(3)}</span>
    </span>
  )
}

function SearchPanel({ collection }: { collection: CollectionOut }) {
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
          placeholder="Ask something the dataset should answer…"
          aria-label="Search query"
          maxLength={2000}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="select"
          aria-label="Results"
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
        >
          {[5, 10, 20, 50].map((n) => (
            <option key={n} value={n}>
              Top {n}
            </option>
          ))}
        </select>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!query.trim() || search.isPending}
        >
          <Icon name={search.isPending ? 'loader' : 'search'} />
          Search
        </button>
      </form>

      {search.error && <div className="hint coll-error">{search.error.message}</div>}

      {found && (
        <>
          <p className="hint">
            {found.hits.length} closest rows to “{found.query}” · {found.took_ms} ms, query embedded
            with {modelLabel(collection.model)}
          </p>
          {found.hits.length === 0 ? (
            <div className="card hub-empty">
              <p className="card-desc">No point comes back for this query.</p>
            </div>
          ) : (
            <ol className="coll-hits">
              {found.hits.map((hit, i) => (
                <li key={hit.row_idx} className="card coll-hit">
                  <div className="coll-hit-head">
                    <span className="coll-rank">#{i + 1}</span>
                    <ScoreMeter score={hit.score} />
                    <Link href={rowHref(collection, hit.row_idx)} className="hint">
                      Row {formatCount(hit.row_idx)}
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
  return (
    <div className="stat-grid hub-stats">
      <div className="card stat">
        <div className="stat-label">Found first</div>
        <div className="stat-val">{percent(result.hit_at_1)}</div>
        <div className="stat-delta">its own row is the top hit</div>
      </div>
      <div className="card stat">
        <div className="stat-label">In the top {result.k}</div>
        <div className="stat-val">{percent(result.hit_at_k)}</div>
        <div className="stat-delta">its own row comes back at all</div>
      </div>
      <div className="card stat">
        <div className="stat-label">Mean reciprocal rank</div>
        <div className="stat-val">{result.mrr.toFixed(2)}</div>
        <div className="stat-delta">1 = always first, 0 = never in the top {result.k}</div>
      </div>
      <div className="card stat">
        <div className="stat-label">Rows tested</div>
        <div className="stat-val">{formatCount(result.queries)}</div>
        <div className="stat-delta">sampled, asking with {result.query_column}</div>
      </div>
    </div>
  )
}

function TestPanel({ collection }: { collection: CollectionOut }) {
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
      <p className="hint coll-lead">
        Sampled rows ask with one of their columns, and a hit is their own row coming back. The
        sample depends on the split and its commit only: collections of the same split, with other
        models or columns, are tested on the same rows.
      </p>
      <form className="hub-toolbar" onSubmit={run}>
        <label className="label" htmlFor="coll-test-column">
          Ask with
        </label>
        <select
          id="coll-test-column"
          className="select mono"
          value={column}
          onChange={(e) => setColumn(e.target.value)}
        >
          {!collection.query_column && <option value="">Pick a column</option>}
          {(collection.fields ?? []).map((field) => (
            <option key={field} value={field}>
              {field}
            </option>
          ))}
        </select>
        <select
          className="select"
          aria-label="Rows to test"
          value={sample}
          onChange={(e) => setSample(Number(e.target.value))}
        >
          {[50, 100, 200, 500].map((n) => (
            <option key={n} value={n}>
              {n} rows
            </option>
          ))}
        </select>
        <select
          className="select"
          aria-label="Top k"
          value={k}
          onChange={(e) => setK(Number(e.target.value))}
        >
          {[1, 5, 10, 20, 50].map((n) => (
            <option key={n} value={n}>
              Top {n}
            </option>
          ))}
        </select>
        <button type="submit" className="btn btn-primary" disabled={!column || evaluate.isPending}>
          <Icon name={evaluate.isPending ? 'loader' : 'play'} />
          Run the test
        </button>
      </form>

      {!result && !evaluate.isPending && (
        <div className="card hub-empty">
          <p className="card-desc">
            Not tested yet. With a Q/A split, embed the answers and ask with the questions: the test
            then shows how often a question finds its own answer, and which rows get confused.
          </p>
        </div>
      )}

      {result && (
        <>
          {result.trivial && (
            <div className="hub-notice coll-warn-box">
              <Icon name="alert" />
              <span>
                <span className="mono">{result.query_column}</span> is embedded too, so every row
                finds itself. Build a collection of the answers alone to test retrieval.
              </span>
            </div>
          )}
          <Metrics result={result} />
          <p className="hint">
            Tested {timeAgo(result.evaluated_at, now)} on {formatCount(result.queries)} of{' '}
            {formatCount(result.sample)} sampled rows, top {result.k}.
          </p>
          {result.misses.length > 0 ? (
            <Misses collection={collection} result={result} />
          ) : (
            <p className="hint">Every tested row found its own row first.</p>
          )}
        </>
      )}
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
  return (
    <div className="card coll-misses">
      <div className="card-head">
        <div>
          <div className="card-title">Rows not found first</div>
          <p className="card-desc">
            {result.misses.length === 20 ? 'The first 20: ' : ''}what each row asked, its own text,
            and the row that came first instead. A near-identical top hit is often the same pair
            twice.
          </p>
        </div>
      </div>
      <div className="coll-table-wrap">
        <table className="table stack-table">
          <thead>
            <tr>
              <th>Asked</th>
              <th>Its own row</th>
              <th>Came first instead</th>
              <th className="coll-num">Rank</th>
            </tr>
          </thead>
          <tbody>
            {result.misses.map((miss) => (
              <tr key={miss.row_idx}>
                <td data-label="Asked">{miss.query}</td>
                <td data-label="Its own row">
                  <Link href={rowHref(collection, miss.row_idx)} className="hint">
                    Row {formatCount(miss.row_idx)}
                  </Link>
                  <div className="coll-cell-text">{miss.expected}</div>
                </td>
                <td data-label="Came first instead">
                  {miss.top_row_idx != null ? (
                    <>
                      <span className="coll-top-head">
                        <Link href={rowHref(collection, miss.top_row_idx)} className="hint">
                          Row {formatCount(miss.top_row_idx)}
                        </Link>
                        {miss.top_score != null && <ScoreMeter score={miss.top_score} />}
                        {miss.top_score != null && miss.top_score >= DUPLICATE_SCORE && (
                          <span className="badge badge-warning">Possible duplicate</span>
                        )}
                      </span>
                      <div className="coll-cell-text">{miss.top_text}</div>
                    </>
                  ) : (
                    <span className="hint">Nothing came back</span>
                  )}
                </td>
                <td className="coll-num mono" data-label="Rank">
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
  const snippet = pythonSnippet(collection)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(snippet)
      toast.success('Copied')
    } catch {
      toast.error("Couldn't copy: select the code instead")
    }
  }
  return (
    <div className="coll-panel">
      <p className="hint coll-lead">
        The vectors are a plain Qdrant collection: query it from your own code with the same model,
        embedding the query the way the build embedded the rows. Each point&apos;s payload holds{' '}
        <span className="mono">row_idx</span>, the embedded <span className="mono">text</span> and
        its <span className="mono">fields</span>.
      </p>
      <div className="card coll-snippet">
        <div className="coll-snippet-head">
          <span className="mono">{collection.qdrant_collection}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={copy}>
            <Icon name="copy" />
            Copy
          </button>
        </div>
        <pre className="mono">{snippet}</pre>
      </div>
    </div>
  )
}

export function CollectionPage({ id }: { id: string }) {
  const collection = useCollection(id)
  const [tab, setTab] = useState<Tab>('search')
  const status = errorStatus(collection.error)

  const back = (
    <Link href="/collections" className="btn btn-ghost btn-sm hub-back">
      <Icon name="chevronLeft" />
      Collections
    </Link>
  )

  if (collection.isPending) {
    return (
      <div className="hub-page coll-page">
        {back}
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          Loading the collection…
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
            <div className="card-title">
              {status === 404 ? 'Collection not found' : "Couldn't load this collection"}
            </div>
            <p className="card-desc">{collection.error.message}</p>
          </div>
          {status !== 404 && (
            <button type="button" className="btn btn-outline" onClick={() => collection.refetch()}>
              <Icon name="refresh" />
              Try again
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
      <NewerCommit collection={c} />

      {c.status === 'ready' && (
        <>
          <nav className="tabs hub-tabs" aria-label="Collection sections">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                className={cn('tab', tab === t.key && 'active')}
                aria-current={tab === t.key ? 'page' : undefined}
                onClick={() => setTab(t.key)}
              >
                <Icon name={t.icon} />
                {t.label}
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
