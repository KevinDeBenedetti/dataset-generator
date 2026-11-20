'use client'

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { errorStatus, type HubRepoRef, type HubRowFilter } from '@/api/sdk'
import type { HubColumnStats, HubDatasetDetail, HubNumericSummary } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { useHubStatistics } from '@/hooks'
import { BarList, Histogram, HistogramTable } from './charts'
import { formatCount, formatPercent, formatValue } from './format'
import { resolveView } from './data-viewer'
import type { HubViewState } from './url-state'
import { rich } from '@/lib/rich'

type Update = (patch: Partial<HubViewState>) => void

function SummaryLine({ summary, unit }: { summary: HubNumericSummary; unit?: string }) {
  const t = useTranslations('viewer')
  const locale = useLocale()
  const suffix = unit ? ` ${unit}` : ''
  return (
    <dl className="hub-summary">
      <div>
        <dt>{t('stats.min')}</dt>
        <dd>{formatValue(summary.min, locale)}</dd>
      </div>
      <div>
        <dt>{t('stats.median')}</dt>
        <dd>{formatValue(summary.median, locale)}</dd>
      </div>
      <div>
        <dt>{t('stats.mean')}</dt>
        <dd>{formatValue(summary.mean, locale)}</dd>
      </div>
      <div>
        <dt>{t('stats.max')}</dt>
        <dd>
          {formatValue(summary.max, locale)}
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
  const t = useTranslations('viewer')
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
            {asTable ? t('stats.chart') : t('stats.table')}
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
  const t = useTranslations('viewer')
  const locale = useLocale()
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
          {t('stats.emptyCount', {
            count: formatCount(column.null_count, locale),
            share: formatPercent(column.null_count, rows, locale),
          })}
        </p>
      )}

      {categories && (
        <>
          <BarList
            label={
              listItems
                ? t('stats.itemsOf', { column: column.name })
                : t('stats.valuesOf', { column: column.name })
            }
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
            selectHint={t('stats.showRows')}
            onSelect={(key) =>
              onFilter({
                column: column.name,
                op: listItems ? 'contains' : 'eq',
                value: JSON.parse(key),
              })
            }
          />
          <p className="hint">
            {t(listItems ? 'stats.distinctItems' : 'stats.distinctValues', {
              count: categories.distinct,
              formatted: formatCount(categories.distinct, locale),
            })}
            {categories.other_count > 0 &&
              ` · ${t(listItems ? 'stats.othersItems' : 'stats.othersRows', {
                count: categories.other_count,
                formatted: formatCount(categories.other_count, locale),
              })}`}
          </p>
        </>
      )}

      {column.lengths && (
        <Distribution
          summary={column.lengths}
          label={listItems ? t('stats.itemsPerValue') : t('stats.charsPerValue')}
          unit={listItems ? t('stats.unitItems') : t('stats.unitChars')}
          integer
        />
      )}

      {column.number && (
        <Distribution summary={column.number} label={t('stats.values')} integer={false} />
      )}

      {column.booleans && (
        <BarList
          label={t('stats.valuesOf', { column: column.name })}
          total={column.booleans.true + column.booleans.false}
          items={[
            { key: 'true', label: 'true', count: column.booleans.true },
            { key: 'false', label: 'false', count: column.booleans.false },
          ]}
          selectHint={t('stats.showRows')}
          onSelect={(key) => onFilter({ column: column.name, op: 'eq', value: key === 'true' })}
        />
      )}

      {!categories && !column.lengths && !column.number && !column.booleans && (
        <p className="hint">{t('stats.noDistribution', { kind: column.kind })}</p>
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
  const t = useTranslations('viewer')
  const locale = useLocale()
  const current = resolveView(detail.views, state.config, state.split)
  const statistics = useHubStatistics(
    repo,
    { revision: detail.sha, config: current?.config ?? null, split: current?.split ?? null },
    current != null,
  )

  if (!current) {
    return <p className="muted">{t('stats.noDataFile')}</p>
  }
  if (statistics.isPending) {
    return (
      <div className="card hub-loading" aria-busy="true">
        <Icon name="loader" className="animate-spin" />
        {t('stats.profiling', { split: current.split })}
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
            {errorStatus(statistics.error) === 413 ? t('stats.tooLarge') : t('stats.computeFailed')}
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
          <div className="stat-label">{t('stats.rows')}</div>
          <div className="stat-val">{formatCount(data.num_rows, locale)}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">{t('stats.columns')}</div>
          <div className="stat-val">{formatCount(data.num_columns, locale)}</div>
        </div>
        <div className="card stat">
          <div className="stat-label">{t('stats.emptyCells')}</div>
          <div className="stat-val">{formatCount(emptyCells, locale)}</div>
          <div className="stat-delta">
            {t('stats.ofAllCells', { share: formatPercent(emptyCells, cells, locale) })}
          </div>
        </div>
        {data.duplicates ? (
          <div className="card stat">
            <div className="stat-label">
              {t('stats.repeated', { column: data.duplicates.column })}
            </div>
            <div className="stat-val">{formatCount(data.duplicates.duplicate_rows, locale)}</div>
            <div className="stat-delta">{t('stats.caseIgnored')}</div>
          </div>
        ) : (
          <div className="card stat">
            <div className="stat-label">{t('stats.split')}</div>
            <div className="stat-val hub-stat-text">{current.split}</div>
          </div>
        )}
      </div>

      <p className="hint hub-stats-note">
        {t.rich(detail.views.length > 1 ? 'stats.profileNoteMulti' : 'stats.profileNote', {
          split: current.split,
          b: rich.b,
        })}
      </p>

      <div className="hub-cols">
        {data.columns.map((column) => (
          <ColumnCard key={column.name} column={column} rows={data.num_rows} onFilter={showRows} />
        ))}
      </div>
    </div>
  )
}
