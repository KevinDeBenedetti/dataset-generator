'use client'

import { useState } from 'react'
import { errorStatus, type HubRepoRef, type HubRowFilter } from '@/api/sdk'
import type { HubColumnStats, HubDatasetDetail, HubNumericSummary } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { useHubStatistics } from '@/hooks'
import { BarList, Histogram, HistogramTable } from './charts'
import { formatCount, formatPercent, formatValue } from './format'
import { resolveView } from './data-viewer'
import type { HubViewState } from './url-state'

type Update = (patch: Partial<HubViewState>) => void

function SummaryLine({ summary, unit }: { summary: HubNumericSummary; unit?: string }) {
  const suffix = unit ? ` ${unit}` : ''
  return (
    <dl className="hub-summary">
      <div>
        <dt>min</dt>
        <dd>{formatValue(summary.min)}</dd>
      </div>
      <div>
        <dt>median</dt>
        <dd>{formatValue(summary.median)}</dd>
      </div>
      <div>
        <dt>mean</dt>
        <dd>{formatValue(summary.mean)}</dd>
      </div>
      <div>
        <dt>max</dt>
        <dd>
          {formatValue(summary.max)}
          {suffix}
        </dd>
      </div>
    </dl>
  )
}

function Distribution({
  summary,
  label,
  unit,
  integer,
}: {
  summary: HubNumericSummary
  label: string
  unit?: string
  integer: boolean
}) {
  const [asTable, setAsTable] = useState(false)
  const bins = summary.histogram ?? []
  return (
    <div className="hub-dist">
      <div className="hub-dist-head">
        <span className="hint">{label}</span>
        {bins.length > 0 && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setAsTable((v) => !v)}
            aria-pressed={asTable}
          >
            <Icon name={asTable ? 'activity' : 'table'} className="ic-sm" />
            {asTable ? 'Chart' : 'Table'}
          </button>
        )}
      </div>
      {asTable ? (
        <HistogramTable bins={bins} unit={unit} integer={integer} />
      ) : (
        <Histogram bins={bins} label={label} unit={unit} integer={integer} />
      )}
      <SummaryLine summary={summary} unit={unit} />
    </div>
  )
}

function ColumnCard({
  column,
  rows,
  onFilter,
}: {
  column: HubColumnStats
  rows: number
  onFilter: (filter: HubRowFilter) => void
}) {
  const categories = column.categories
  const listItems = column.kind === 'list'
  return (
    <section className="card hub-col">
      <header className="hub-col-head">
        <div>
          <h3 className="hub-col-name mono">{column.name}</h3>
          <div className="hint mono">{column.type}</div>
        </div>
        <span className="hub-th-kind">{column.kind}</span>
      </header>

      {column.null_count > 0 && (
        <p className="hint">
          {formatCount(column.null_count)} empty ({formatPercent(column.null_count, rows)})
        </p>
      )}

      {categories && (
        <>
          <BarList
            label={`${listItems ? 'Items' : 'Values'} of ${column.name}`}
            total={
              listItems
                ? categories.values.reduce((s, v) => s + v.count, 0) + categories.other_count
                : rows
            }
            items={categories.values.map((v) => ({
              key: JSON.stringify(v.value),
              label: String(v.value),
              count: v.count,
            }))}
            selectHint="Show these rows"
            onSelect={(key) =>
              onFilter({
                column: column.name,
                op: listItems ? 'contains' : 'eq',
                value: JSON.parse(key),
              })
            }
          />
          <p className="hint">
            {formatCount(categories.distinct)} distinct {listItems ? 'items' : 'values'}
            {categories.other_count > 0 &&
              ` · ${formatCount(categories.other_count)} ${listItems ? 'items' : 'rows'} in the others`}
          </p>
        </>
      )}

      {column.lengths && (
        <Distribution
          summary={column.lengths}
          label={listItems ? 'Items per value' : 'Characters per value'}
          unit={listItems ? 'items' : 'chars'}
          integer
        />
      )}

      {column.number && <Distribution summary={column.number} label="Values" integer={false} />}

      {column.booleans && (
        <BarList
          label={`Values of ${column.name}`}
          total={column.booleans.true + column.booleans.false}
          items={[
            { key: 'true', label: 'true', count: column.booleans.true },
            { key: 'false', label: 'false', count: column.booleans.false },
          ]}
          selectHint="Show these rows"
          onSelect={(key) => onFilter({ column: column.name, op: 'eq', value: key === 'true' })}
        />
      )}

      {!categories && !column.lengths && !column.number && !column.booleans && (
        <p className="hint">No distribution for {column.kind} values.</p>
      )}
    </section>
  )
}

export function StatsPanel({
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
  const current = resolveView(detail.views, state.config, state.split)
  const statistics = useHubStatistics(
    repo,
    { revision: detail.sha, config: current?.config ?? null, split: current?.split ?? null },
    current != null,
  )

  if (!current) {
    return <p className="muted">This revision has no data file to profile.</p>
  }
  if (statistics.isPending) {
    return (
      <div className="card hub-loading" aria-busy="true">
        <Icon name="loader" className="animate-spin" />
        Profiling the {current.split} split…
      </div>
    )
  }
  if (statistics.error) {
    return (
      <div className="card hub-empty">
        <span className="cell-ic ic-lg">
          <Icon name="alert" className="ic-lg" />
        </span>
        <div>
          <div className="card-title">
            {errorStatus(statistics.error) === 413
              ? 'Too large to profile in the app'
              : "Couldn't compute the statistics"}
          </div>
          <p className="card-desc">{statistics.error.message}</p>
        </div>
      </div>
    )
  }

  const data = statistics.data
  const emptyCells = data.columns.reduce((sum, c) => sum + c.null_count, 0)
  const cells = data.num_rows * data.num_columns
  const showRows = (filter: HubRowFilter) =>
    update({
      tab: 'data',
      config: current.config,
      split: current.split,
      filters: [filter],
      q: '',
      row: null,
    })

  return (
    <div className="hub-stats-tab">
      <div className="stat-grid hub-stats">
        <div className="card stat">
          <div className="stat-label">Rows</div>
          <div className="stat-val">{formatCount(data.num_rows)}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Columns</div>
          <div className="stat-val">{formatCount(data.num_columns)}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Empty cells</div>
          <div className="stat-val">{formatCount(emptyCells)}</div>
          <div className="stat-delta">{formatPercent(emptyCells, cells)} of all cells</div>
        </div>
        {data.duplicates ? (
          <div className="card stat">
            <div className="stat-label">Repeated {data.duplicates.column}s</div>
            <div className="stat-val">{formatCount(data.duplicates.duplicate_rows)}</div>
            <div className="stat-delta">case and spacing ignored</div>
          </div>
        ) : (
          <div className="card stat">
            <div className="stat-label">Split</div>
            <div className="stat-val hub-stat-text">{current.split}</div>
          </div>
        )}
      </div>

      <p className="hint hub-stats-note">
        Profile of the <b>{current.split}</b> split
        {detail.views.length > 1 ? ' (switch splits on the Data tab)' : ''}. Click a value to see
        its rows.
      </p>

      <div className="hub-cols">
        {data.columns.map((column) => (
          <ColumnCard key={column.name} column={column} rows={data.num_rows} onFilter={showRows} />
        ))}
      </div>
    </div>
  )
}
