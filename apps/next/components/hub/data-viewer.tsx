'use client'

import { type FormEvent, useEffect, useId, useMemo, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import {
  errorStatus,
  type HubFilterOp,
  type HubRepoRef,
  type HubRowFilter,
  type HubRowsQuery,
} from '@/api/sdk'
import type {
  HubColumnStats,
  HubDatasetDetail,
  HubFeature,
  HubQaColumns,
  HubRow,
  HubView,
} from '@/api/types'
import { Icon } from '@/components/app/icon'
import { useHubRows, useHubStatistics } from '@/hooks'
import { cn } from '@/lib/utils'
import { MiniHistogram } from './charts'
import {
  compactJson,
  formatBytes,
  formatCount,
  formatPercent,
  formatValue,
  isHttpUrl,
} from './format'
import { RowDrawer } from './row-drawer'
import { PAGE_SIZES, type HubViewState } from './url-state'

type Update = (patch: Partial<HubViewState>) => void
type Translate = ReturnType<typeof useTranslations<'viewer'>>

// --- tables of the dataset -------------------------------------------------------

/** The table the URL asks for, else the dataset's default one. */
export function resolveView(
  views: HubView[],
  config: string | null,
  split: string | null,
): HubView | null {
  return (
    views.find(
      (v) => (config == null || v.config === config) && (split == null || v.split === split),
    ) ??
    views[0] ??
    null
  )
}

function SplitPicker({
  views,
  current,
  update,
}: {
  views: HubView[]
  current: HubView
  update: Update
}) {
  const t = useTranslations('viewer')
  const locale = useLocale()
  const configs = [...new Set(views.map((v) => v.config))]
  const splits = views.filter((v) => v.config === current.config)
  if (views.length < 2) return null
  return (
    <div className="hub-splits">
      {configs.length > 1 && (
        <select
          className="select hub-config"
          aria-label={t('dataViewer.config')}
          value={current.config}
          onChange={(e) => {
            const first = views.find((v) => v.config === e.target.value)
            update({ config: e.target.value, split: first?.split ?? null, row: null })
          }}
        >
          {configs.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      )}
      <div className="tabs" role="tablist" aria-label={t('dataViewer.split')}>
        {splits.map((v) => (
          <button
            key={`${v.config}/${v.split}`}
            type="button"
            role="tab"
            aria-selected={v.split === current.split}
            className={cn('tab', v.split === current.split && 'active')}
            onClick={() => update({ config: v.config, split: v.split, row: null })}
            title={v.files.join('\n')}
          >
            {v.split}
            {v.extra && <span className="hub-extra">{t('dataViewer.extra')}</span>}
            {v.num_bytes != null && (
              <span className="mono muted">{formatBytes(v.num_bytes, locale)}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

// --- filters --------------------------------------------------------------------------

// Comparisons read the same in every language; the other conditions are
// messages (`dataViewer.ops.*`).
const OP_SYMBOLS = { lt: '<', lte: '≤', gt: '>', gte: '≥' } as const
type SymbolOp = keyof typeof OP_SYMBOLS

function opLabel(op: HubFilterOp, t: Translate): string {
  if (op in OP_SYMBOLS) return OP_SYMBOLS[op as SymbolOp]
  return t(`dataViewer.ops.${op as Exclude<HubFilterOp, SymbolOp>}`)
}

const OPS_BY_KIND: Record<string, HubFilterOp[]> = {
  string: ['eq', 'ne', 'contains', 'null', 'not_null'],
  number: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'null', 'not_null'],
  bool: ['eq', 'ne', 'null', 'not_null'],
  list: ['contains', 'null', 'not_null'],
}

function needsValue(op: HubFilterOp): boolean {
  return op !== 'null' && op !== 'not_null'
}

function describeFilter(filter: HubRowFilter, t: Translate): string {
  const value = needsValue(filter.op) ? ` ${String(filter.value)}` : ''
  return `${filter.column} ${opLabel(filter.op, t)}${value}`
}

function FilterForm({
  features,
  stats,
  onAdd,
  onCancel,
}: {
  features: HubFeature[]
  stats: Map<string, HubColumnStats>
  onAdd: (filter: HubRowFilter) => void
  onCancel: () => void
}) {
  const t = useTranslations('viewer')
  const tc = useTranslations('common')
  const locale = useLocale()
  const filterable = features.filter((f) => f.kind in OPS_BY_KIND)
  const [column, setColumn] = useState(filterable[0]?.name ?? '')
  const kind = filterable.find((f) => f.name === column)?.kind ?? 'string'
  const ops = OPS_BY_KIND[kind] ?? []
  const [op, setOp] = useState<HubFilterOp>(ops[0] ?? 'eq')
  const [value, setValue] = useState('')
  const listId = useId()
  const known = stats.get(column)?.categories?.values ?? []
  const effectiveOp = ops.includes(op) ? op : (ops[0] ?? 'eq')

  if (filterable.length === 0) {
    return <p className="hint">{t('dataViewer.noFilterableColumn')}</p>
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (needsValue(effectiveOp) && value.trim() === '') return
    let parsed: string | number | boolean | null = needsValue(effectiveOp) ? value.trim() : null
    if (kind === 'number' && parsed != null) parsed = Number(parsed)
    if (kind === 'bool' && parsed != null) parsed = parsed === 'true'
    if (typeof parsed === 'number' && Number.isNaN(parsed)) return
    onAdd({ column, op: effectiveOp, value: parsed })
  }

  return (
    <form className="hub-filter-form" onSubmit={submit}>
      <select
        className="select"
        aria-label={t('dataViewer.column')}
        value={column}
        onChange={(e) => {
          setColumn(e.target.value)
          setValue('')
        }}
      >
        {filterable.map((f) => (
          <option key={f.name} value={f.name}>
            {f.name}
          </option>
        ))}
      </select>
      <select
        className="select"
        aria-label={t('dataViewer.condition')}
        value={effectiveOp}
        onChange={(e) => setOp(e.target.value as HubFilterOp)}
      >
        {ops.map((o) => (
          <option key={o} value={o}>
            {opLabel(o, t)}
          </option>
        ))}
      </select>
      {needsValue(effectiveOp) &&
        (kind === 'bool' ? (
          <select
            className="select"
            aria-label={t('dataViewer.value')}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          >
            <option value="">{t('dataViewer.choose')}</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : (
          <>
            <input
              className="input"
              aria-label={t('dataViewer.value')}
              placeholder={t('dataViewer.value')}
              type={kind === 'number' ? 'number' : 'text'}
              step="any"
              list={known.length ? listId : undefined}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            {known.length > 0 && (
              <datalist id={listId}>
                {known.map((v) => (
                  <option key={String(v.value)} value={String(v.value)}>
                    {t('dataViewer.rowCount', {
                      count: v.count,
                      formatted: formatCount(v.count, locale),
                    })}
                  </option>
                ))}
              </datalist>
            )}
          </>
        ))}
      <button type="submit" className="btn btn-primary btn-sm">
        {t('dataViewer.apply')}
      </button>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>
        {tc('cancel')}
      </button>
    </form>
  )
}

// --- cells ------------------------------------------------------------------------------

function Cell({ value, truncated }: { value: unknown; truncated: boolean }) {
  const t = useTranslations('viewer')
  const locale = useLocale()
  if (value === null || value === undefined) return <span className="hub-null">null</span>
  if (typeof value === 'boolean') return <span className="tag">{String(value)}</span>
  if (typeof value === 'number') return <span className="mono">{formatValue(value, locale)}</span>
  if (typeof value === 'string') {
    if (value === '') return <span className="hub-null">{t('dataViewer.empty')}</span>
    return (
      <span className={cn('hub-text', isHttpUrl(value) && 'hub-url')}>
        {value}
        {truncated && <span className="muted">…</span>}
      </span>
    )
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="hub-null">[ ]</span>
    const shown = value.slice(0, 3)
    return (
      <span className="hub-chips">
        {shown.map((item, i) => (
          // Items of a list have no identity but their position.
          // oxlint-disable-next-line react/no-array-index-key
          <span key={i} className="tag">
            {typeof item === 'string' ? item : compactJson(item)}
          </span>
        ))}
        {value.length > shown.length && (
          <span className="muted">+{value.length - shown.length}</span>
        )}
      </span>
    )
  }
  return <span className="hub-json mono">{compactJson(value)}</span>
}

function ColumnSummary({ stats, rows }: { stats?: HubColumnStats; rows: number }) {
  const t = useTranslations('viewer')
  const locale = useLocale()
  if (!stats) return null
  if (stats.categories) {
    const top = stats.categories.values[0]
    return (
      <span className="hub-th-sum">
        {t('dataViewer.valueCount', {
          count: stats.categories.distinct,
          formatted: formatCount(stats.categories.distinct, locale),
        })}
        {top && (
          <span className="muted">
            {' '}
            · {String(top.value)} {formatPercent(top.count, rows, locale)}
          </span>
        )}
      </span>
    )
  }
  const summary = stats.number ?? stats.lengths
  if (summary?.histogram?.length) {
    const range = { min: formatValue(summary.min, locale), max: formatValue(summary.max, locale) }
    return (
      <span className="hub-th-sum">
        <MiniHistogram bins={summary.histogram} />
        <span className="muted">
          {stats.lengths && stats.kind === 'string'
            ? t('dataViewer.rangeChars', range)
            : stats.lengths && stats.kind === 'list'
              ? t('dataViewer.rangeItems', range)
              : `${range.min}–${range.max}`}
        </span>
      </span>
    )
  }
  if (stats.booleans) {
    return (
      <span className="hub-th-sum muted">
        true{' '}
        {formatPercent(stats.booleans.true, stats.booleans.true + stats.booleans.false, locale)}
      </span>
    )
  }
  return null
}

const SORTABLE = new Set(['string', 'number', 'bool', 'datetime'])

function RowsTable({
  rows,
  features,
  stats,
  numRows,
  state,
  update,
  onOpen,
}: {
  rows: HubRow[]
  features: HubFeature[]
  stats: Map<string, HubColumnStats>
  numRows: number
  state: HubViewState
  update: Update
  onOpen: (rowIdx: number) => void
}) {
  const t = useTranslations('viewer')
  const cycleSort = (column: string) => {
    if (state.sort !== column) update({ sort: column, order: 'asc' })
    else if (state.order === 'asc') update({ order: 'desc' })
    else update({ sort: null, order: 'asc' })
  }

  return (
    <div className="hub-table-wrap">
      <table className="table hub-table">
        <thead>
          <tr>
            <th className="hub-idx-col">#</th>
            {features.map((f) => {
              const sorted = state.sort === f.name
              return (
                <th
                  key={f.name}
                  aria-sort={sorted ? (state.order === 'asc' ? 'ascending' : 'descending') : 'none'}
                >
                  {SORTABLE.has(f.kind) ? (
                    <button
                      type="button"
                      className="hub-th"
                      onClick={() => cycleSort(f.name)}
                      title={t('dataViewer.sortBy', { column: f.name })}
                    >
                      <span className="hub-th-name">{f.name}</span>
                      <span className="hub-th-kind">{f.kind}</span>
                      {sorted && (
                        <span aria-hidden="true">{state.order === 'asc' ? '↑' : '↓'}</span>
                      )}
                    </button>
                  ) : (
                    <span className="hub-th">
                      <span className="hub-th-name">{f.name}</span>
                      <span className="hub-th-kind">{f.kind}</span>
                    </span>
                  )}
                  <ColumnSummary stats={stats.get(f.name)} rows={numRows} />
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.row_idx}>
              <td className="hub-idx-col">
                {/* Stretched over the whole row: one tab stop per row, and the
                    whole row is the click target. */}
                <button
                  type="button"
                  className="hub-row-open"
                  onClick={() => onOpen(r.row_idx)}
                  aria-label={t('dataViewer.openRow', { index: r.row_idx })}
                >
                  {r.row_idx}
                </button>
              </td>
              {features.map((f) => (
                <td key={f.name} className={cn(f.kind === 'number' && 'num')}>
                  <Cell
                    value={r.row[f.name]}
                    truncated={(r.truncated_cells ?? []).includes(f.name)}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Short string columns worth showing as chips on a Q/A card.
function chipColumns(features: HubFeature[], qa: HubQaColumns, stats: Map<string, HubColumnStats>) {
  const skip = new Set([qa.question, qa.answer, qa.context, 'id'])
  return features.filter(
    (f) =>
      !skip.has(f.name) &&
      ((f.kind === 'string' && stats.get(f.name)?.categories) || f.kind === 'number'),
  )
}

function QACards({
  rows,
  qa,
  chips,
  onOpen,
}: {
  rows: HubRow[]
  qa: HubQaColumns
  chips: HubFeature[]
  onOpen: (rowIdx: number) => void
}) {
  const locale = useLocale()
  return (
    <ol className="hub-qa-list">
      {rows.map((r) => {
        const context = qa.context ? r.row[qa.context] : null
        return (
          <li key={r.row_idx}>
            <button type="button" className="hub-qa" onClick={() => onOpen(r.row_idx)}>
              <span className="hub-qa-head">
                <span className="mono muted">#{r.row_idx}</span>
                {chips.map((f) => {
                  const value = r.row[f.name]
                  if (value === null || value === undefined || value === '') return null
                  return (
                    <span key={f.name} className="tag" title={f.name}>
                      {f.kind === 'number'
                        ? `${f.name} ${formatValue(value as number, locale)}`
                        : String(value)}
                    </span>
                  )
                })}
              </span>
              <span className="hub-qa-q">{String(r.row[qa.question] ?? '')}</span>
              <span className="hub-qa-a">{String(r.row[qa.answer] ?? '')}</span>
              {typeof context === 'string' && context && (
                <span className="hub-qa-c">{context}</span>
              )}
            </button>
          </li>
        )
      })}
    </ol>
  )
}

function Pager({
  page,
  pages,
  size,
  from,
  to,
  matched,
  total,
  update,
}: {
  page: number
  pages: number
  size: number
  from: number
  to: number
  matched: number
  total: number
  update: Update
}) {
  const t = useTranslations('viewer')
  const tc = useTranslations('common')
  const locale = useLocale()
  const range = {
    from: formatCount(from, locale),
    to: formatCount(to, locale),
    matched: formatCount(matched, locale),
    total: formatCount(total, locale),
  }
  const filtered = matched !== total
  return (
    <div className="hub-pager">
      <span className="muted">
        {matched === 0
          ? filtered
            ? t('dataViewer.noRowsFiltered', { total: range.total })
            : t('dataViewer.noRows')
          : filtered
            ? t('dataViewer.rowsRangeFiltered', range)
            : t('dataViewer.rowsRange', {
                from: range.from,
                to: range.to,
                matched: range.matched,
              })}
      </span>
      <div className="hub-pager-nav">
        <select
          className="select hub-size"
          aria-label={t('dataViewer.rowsPerPage')}
          value={size}
          onChange={(e) => update({ size: Number(e.target.value) })}
        >
          {PAGE_SIZES.map((s) => (
            <option key={s} value={s}>
              {t('dataViewer.perPage', { size: s })}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          disabled={page <= 1}
          onClick={() => update({ page: 1, row: null })}
          aria-label={t('dataViewer.firstPage')}
        >
          «
        </button>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          disabled={page <= 1}
          onClick={() => update({ page: page - 1, row: null })}
        >
          <Icon name="chevronLeft" />
          {tc('previous')}
        </button>
        <span className="mono muted">
          {page} / {Math.max(1, pages)}
        </span>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          disabled={page >= pages}
          onClick={() => update({ page: page + 1, row: null })}
        >
          {tc('next')}
          <Icon name="chevronRight" />
        </button>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          disabled={page >= pages}
          onClick={() => update({ page: pages, row: null })}
          aria-label={t('dataViewer.lastPage')}
        >
          »
        </button>
      </div>
    </div>
  )
}

// --- the tab ------------------------------------------------------------------------------

export function DataViewer({
  repo,
  detail,
  state,
  update,
}: {
  repo: HubRepoRef
  detail: HubDatasetDetail
  state: HubViewState
  update: Update
}) {
  const t = useTranslations('viewer')
  const locale = useLocale()
  const current = resolveView(detail.views, state.config, state.split)
  // Rows are read at the commit the page was loaded at, so the tables listed
  // above and the rows below always come from the same version.
  const splitQuery = {
    revision: detail.sha,
    config: current?.config ?? null,
    split: current?.split ?? null,
  }
  const rowsQuery: HubRowsQuery = {
    ...splitQuery,
    offset: (state.page - 1) * state.size,
    length: state.size,
    q: state.q || null,
    filters: state.filters,
    sort: state.sort,
    order: state.order,
  }
  const rows = useHubRows(repo, rowsQuery, current != null)
  const statistics = useHubStatistics(repo, splitQuery, current != null)
  const stats = useMemo(
    () => new Map((statistics.data?.columns ?? []).map((c) => [c.name, c])),
    [statistics.data],
  )

  // The search box follows the URL, and writes to it once typing pauses.
  const [query, setQuery] = useState(state.q)
  const [syncedQuery, setSyncedQuery] = useState(state.q)
  if (state.q !== syncedQuery) {
    setSyncedQuery(state.q)
    setQuery(state.q)
  }
  useEffect(() => {
    if (query === state.q) return
    const timer = setTimeout(() => update({ q: query, row: null }), 350)
    return () => clearTimeout(timer)
  }, [query, state.q, update])

  const [adding, setAdding] = useState(false)

  if (!current) {
    return (
      <div className="card hub-empty">
        <span className="cell-ic ic-lg">
          <Icon name="fileJson" className="ic-lg" />
        </span>
        <div>
          <div className="card-title">{t('dataViewer.noDataTitle')}</div>
          <p className="card-desc">{t('dataViewer.noDataDesc')}</p>
        </div>
      </div>
    )
  }

  const data = rows.data
  const features = data?.features ?? []
  const qa = data?.qa ?? null
  const layout = state.layout ?? (qa ? 'cards' : 'table')
  const matched = data?.num_rows_matched ?? 0
  const total = data?.num_rows_total ?? 0
  const pages = Math.max(1, Math.ceil(matched / state.size))
  const from = matched ? (state.page - 1) * state.size + 1 : 0
  const to = Math.min(matched, state.page * state.size)
  const status = errorStatus(rows.error)
  const pageRows = data?.rows ?? []
  const openIndex = state.row == null ? -1 : pageRows.findIndex((r) => r.row_idx === state.row)

  return (
    <div className="hub-viewer">
      <SplitPicker views={detail.views} current={current} update={update} />

      <div className="hub-toolbar">
        <label className="hub-search">
          <Icon name="search" />
          <input
            type="search"
            placeholder={t('dataViewer.searchPlaceholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            maxLength={200}
          />
        </label>
        <button
          type="button"
          className="btn btn-outline"
          onClick={() => setAdding((v) => !v)}
          aria-expanded={adding}
        >
          <Icon name="filter" />
          {t('dataViewer.filter')}
        </button>
        {qa && (
          <fieldset className="tabs">
            <legend className="sr-only">{t('dataViewer.layout')}</legend>
            <button
              type="button"
              className={cn('tab', layout === 'cards' && 'active')}
              aria-pressed={layout === 'cards'}
              onClick={() => update({ layout: 'cards' })}
            >
              <Icon name="list" />
              {t('dataViewer.layoutQa')}
            </button>
            <button
              type="button"
              className={cn('tab', layout === 'table' && 'active')}
              aria-pressed={layout === 'table'}
              onClick={() => update({ layout: 'table' })}
            >
              <Icon name="table" />
              {t('dataViewer.layoutTable')}
            </button>
          </fieldset>
        )}
      </div>

      {adding && features.length > 0 && (
        <FilterForm
          features={features}
          stats={stats}
          onCancel={() => setAdding(false)}
          onAdd={(filter) => {
            update({ filters: [...state.filters, filter], row: null })
            setAdding(false)
          }}
        />
      )}

      {(state.filters.length > 0 || state.sort) && (
        <div className="hub-chips hub-active">
          {state.filters.map((filter, index) => (
            <button
              type="button"
              // Filters are a list the user builds; position is their identity.
              // oxlint-disable-next-line react/no-array-index-key
              key={index}
              className="hub-chip"
              onClick={() =>
                update({ filters: state.filters.filter((_, i) => i !== index), row: null })
              }
              aria-label={t('dataViewer.removeFilter', { filter: describeFilter(filter, t) })}
            >
              {describeFilter(filter, t)}
              <Icon name="x" className="ic-sm" />
            </button>
          ))}
          {state.sort && (
            <button
              type="button"
              className="hub-chip"
              onClick={() => update({ sort: null, order: 'asc' })}
              aria-label={t('dataViewer.removeSorting')}
            >
              {t('dataViewer.sortedBy', {
                column: state.sort,
                arrow: state.order === 'asc' ? '↑' : '↓',
              })}
              <Icon name="x" className="ic-sm" />
            </button>
          )}
          {state.filters.length > 1 && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => update({ filters: [], row: null })}
            >
              {t('dataViewer.clearFilters')}
            </button>
          )}
        </div>
      )}

      {rows.isPending && (
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          {current.num_bytes != null
            ? t('dataViewer.loadingSized', {
                split: current.split,
                size: formatBytes(current.num_bytes, locale),
              })
            : t('dataViewer.loading', { split: current.split })}
        </div>
      )}

      {rows.error && !data && (
        <div className="card hub-empty">
          <span className="cell-ic ic-lg">
            <Icon name="alert" className="ic-lg" />
          </span>
          <div>
            <div className="card-title">
              {status === 413
                ? t('dataViewer.errors.tooLarge')
                : status === 422
                  ? t('dataViewer.errors.notTabular')
                  : status === 400
                    ? t('dataViewer.errors.badFilter')
                    : t('dataViewer.errors.loadFailed')}
            </div>
            <p className="card-desc">{rows.error.message}</p>
          </div>
          {status === 413 ? (
            <a
              className="btn btn-outline"
              href={`${detail.url}/viewer/${encodeURIComponent(current.config)}/${encodeURIComponent(current.split)}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Icon name="external" />
              {t('dataViewer.openOnHub')}
            </a>
          ) : status === 400 ? (
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => update({ filters: [], sort: null, q: '' })}
            >
              {t('dataViewer.clearFilters')}
            </button>
          ) : (
            <button type="button" className="btn btn-outline" onClick={() => rows.refetch()}>
              <Icon name="refresh" />
              {t('dataViewer.tryAgain')}
            </button>
          )}
        </div>
      )}

      {data && (
        <div className={cn('hub-results', rows.isPlaceholderData && 'is-stale')}>
          {pageRows.length === 0 ? (
            <div className="card hub-empty">
              <span className="cell-ic ic-lg">
                <Icon name="search" className="ic-lg" />
              </span>
              <div>
                <div className="card-title">{t('dataViewer.noMatchTitle')}</div>
                <p className="card-desc">
                  {total === 0
                    ? t('dataViewer.emptySplit')
                    : t('dataViewer.noMatchDesc', { total: formatCount(total, locale) })}
                </p>
              </div>
              {total > 0 && (
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => update({ filters: [], q: '' })}
                >
                  {t('dataViewer.clearSearchAndFilters')}
                </button>
              )}
            </div>
          ) : layout === 'cards' && qa ? (
            <QACards
              rows={pageRows}
              qa={qa}
              chips={chipColumns(features, qa, stats)}
              onOpen={(row) => update({ row })}
            />
          ) : (
            <RowsTable
              rows={pageRows}
              features={features}
              stats={stats}
              numRows={total}
              state={state}
              update={update}
              onOpen={(row) => update({ row })}
            />
          )}
          <Pager
            page={state.page}
            pages={pages}
            size={state.size}
            from={from}
            to={to}
            matched={matched}
            total={total}
            update={update}
          />
        </div>
      )}

      {openIndex >= 0 && data && (
        <RowDrawer
          repo={repo}
          splitQuery={splitQuery}
          split={current.split}
          row={pageRows[openIndex]}
          features={features}
          qa={qa}
          onClose={() => update({ row: null })}
          onPrev={openIndex > 0 ? () => update({ row: pageRows[openIndex - 1].row_idx }) : null}
          onNext={
            openIndex < pageRows.length - 1
              ? () => update({ row: pageRows[openIndex + 1].row_idx })
              : null
          }
        />
      )}
    </div>
  )
}
