'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import type { TabularDraft } from '@/api/sdk'
import {
  useDraftRows,
  useReviewDraft,
  useSaveRecipeSteps,
  useTabularDraft,
} from '@/hooks/use-tabular-review'
import { cn } from '@/lib/utils'
import { percent, reviewState, withStep } from './review-state'

const TABS = ['schema', 'sample', 'quality', 'changes'] as const
type Tab = (typeof TABS)[number]
const PAGE = 50

function cell(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function SchemaTab({ draft }: { draft: TabularDraft }) {
  const t = useTranslations('review.tabular')
  const locale = useLocale()
  const columns = draft.profile.columns ?? {}
  const rows = draft.rows || 1
  return (
    <table className="table">
      <thead>
        <tr>
          <th>{t('column')}</th>
          <th>{t('type')}</th>
          <th>{t('empty')}</th>
          <th>{t('distinct')}</th>
          <th>{t('range')}</th>
        </tr>
      </thead>
      <tbody>
        {draft.schema.map((column) => {
          const p = columns[column.name]
          return (
            <tr key={column.name}>
              <td>
                <span className="mono">{column.name}</span>
                {column.original && column.original !== column.name && (
                  <div className="hint">{column.original}</div>
                )}
              </td>
              <td className="mono">{column.type}</td>
              <td>{p ? percent(p.nb_missing_values / rows, locale) : '—'}</td>
              <td>{p?.nb_distinct ?? '—'}</td>
              <td className="mono">
                {p && p.min !== undefined ? `${cell(p.min)} – ${cell(p.max)}` : '—'}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function SampleTab({ draft }: { draft: TabularDraft }) {
  const t = useTranslations('review.tabular')
  const [offset, setOffset] = useState(0)
  const [sort, setSort] = useState<string | null>(null)
  const [desc, setDesc] = useState(false)
  const [filterColumn, setFilterColumn] = useState(draft.schema[0]?.name ?? '')
  const [filterValue, setFilterValue] = useState('')
  const { data, isFetching, error } = useDraftRows(draft.run_id, {
    offset,
    limit: PAGE,
    sort,
    desc,
    filter_column: filterColumn,
    filter_value: filterValue,
  })
  const total = data?.total ?? 0
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <label className="hint" htmlFor="filter-column">
          {t('filter')}
        </label>
        <select
          id="filter-column"
          className="input"
          value={filterColumn}
          onChange={(e) => {
            setFilterColumn(e.target.value)
            setOffset(0)
          }}
        >
          {draft.schema.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          className="input"
          value={filterValue}
          placeholder={t('contains')}
          onChange={(e) => {
            setFilterValue(e.target.value)
            setOffset(0)
          }}
        />
        <span className="hint">
          {t('rowsRange', {
            from: total ? offset + 1 : 0,
            to: Math.min(offset + PAGE, total),
            total,
          })}
          {isFetching && ' …'}
        </span>
        <button
          className="btn btn-outline btn-sm"
          type="button"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE))}
        >
          {t('previous')}
        </button>
        <button
          className="btn btn-outline btn-sm"
          type="button"
          disabled={offset + PAGE >= total}
          onClick={() => setOffset(offset + PAGE)}
        >
          {t('next')}
        </button>
      </div>
      {error && <p className="hint">{error.message}</p>}
      <div style={{ overflowX: 'auto' }}>
        <table className="table">
          <thead>
            <tr>
              {(data?.columns ?? draft.schema.map((c) => c.name)).map((name) => (
                <th key={name}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm mono"
                    onClick={() => {
                      if (sort === name) setDesc(!desc)
                      else {
                        setSort(name)
                        setDesc(false)
                      }
                      setOffset(0)
                    }}
                  >
                    {name}
                    {sort === name ? (desc ? ' ↓' : ' ↑') : ''}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.rows ?? []).map((row, i) => (
              // A page's rows have no id of their own: their position is it.
              // oxlint-disable-next-line react/no-array-index-key
              <tr key={offset + i}>
                {(data?.columns ?? []).map((name) => (
                  <td key={name} className="mono">
                    {cell(row[name])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function QualityTab({ draft }: { draft: TabularDraft }) {
  const t = useTranslations('review.tabular')
  const locale = useLocale()
  const save = useSaveRecipeSteps()
  const [steps, setSteps] = useState(draft.steps)
  const report = draft.quality_report
  const s = report.structure
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <section>
        <h3 className="card-title">{t('personalData')}</h3>
        {(report.pii ?? []).length === 0 ? (
          <p className="hint">{t('noPersonalData')}</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>{t('column')}</th>
                <th>{t('kind')}</th>
                <th>{t('share')}</th>
                <th>{t('action')}</th>
              </tr>
            </thead>
            <tbody>
              {(report.pii ?? []).map((c) => {
                const added = steps.some(
                  (step) => JSON.stringify(step) === JSON.stringify(c.suggested_step),
                )
                return (
                  <tr key={`${c.column}:${c.kind}`}>
                    <td className="mono">{c.column}</td>
                    <td>{c.reason}</td>
                    <td>{percent(c.share, locale)}</td>
                    <td>
                      {c.masked ? (
                        <span className="badge badge-success">{t('masked')}</span>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          disabled={!draft.recipe_id || added || save.isPending}
                          onClick={() => {
                            const next = withStep(steps, c.suggested_step)
                            save.mutate(
                              { recipeId: draft.recipe_id ?? '', steps: next },
                              {
                                onSuccess: () => {
                                  setSteps(next)
                                  toast.success(t('maskAdded'))
                                },
                                onError: (e: Error) => toast.error(e.message),
                              },
                            )
                          }}
                        >
                          {added ? t('maskInRecipe') : t('addMask')}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
      {s && (
        <section>
          <h3 className="card-title">{t('structure')}</h3>
          <ul className="hint">
            <li>{t('emptyColumns', { columns: s.empty_columns.join(', ') || '—' })}</li>
            <li>{t('constantColumns', { columns: s.constant_columns.join(', ') || '—' })}</li>
            <li>
              {t('mostlyEmpty', {
                columns:
                  s.mostly_empty_columns
                    .map((c) => `${c.column} (${percent(c.share, locale)})`)
                    .join(', ') || '—',
              })}
            </li>
            <li>{t('duplicates', { count: s.duplicated_rows })}</li>
            {s.rows_change !== null && (
              <li>{t('rowsChange', { change: percent(s.rows_change, locale) })}</li>
            )}
          </ul>
        </section>
      )}
      <section>
        <h3 className="card-title">{t('rules')}</h3>
        <ul>
          {(report.rules ?? []).map((rule) => (
            <li key={`${rule.rule}:${rule.column ?? ''}:${rule.message}`}>
              <span
                className={cn(
                  'badge',
                  rule.status === 'pass'
                    ? 'badge-success'
                    : rule.status === 'block'
                      ? 'badge-destructive'
                      : 'badge-warning',
                )}
              >
                {t(`status.${rule.status}`)}
              </span>{' '}
              <span className="mono">{rule.rule}</span> {rule.message}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

function ChangesTab({ draft }: { draft: TabularDraft }) {
  const t = useTranslations('review.tabular')
  const c = draft.changes
  if (!c) return <p className="hint">{t('firstVersion')}</p>
  return (
    <ul>
      <li>{t('rowsBeforeAfter', { before: c.rows_before ?? '—', after: c.rows_after ?? '—' })}</li>
      <li>{t('added', { columns: c.added.join(', ') || '—' })}</li>
      <li>{t('removed', { columns: c.removed.join(', ') || '—' })}</li>
      <li>
        {t('retyped', {
          columns: c.retyped.map((r) => `${r.column}: ${r.from} → ${r.to}`).join(', ') || '—',
        })}
      </li>
    </ul>
  )
}

// The review of a recipe run's tabular draft: its shape, a sample, its
// quality report and its changes, then approve or reject (ADR 0006).
export function TabularReview({ runId }: { runId: string }) {
  const t = useTranslations('review.tabular')
  const { data: draft, error, isPending } = useTabularDraft(runId)
  const review = useReviewDraft(runId)
  const [tab, setTab] = useState<Tab>('schema')
  const [comment, setComment] = useState('')
  const state = reviewState(draft)

  if (isPending) return <p className="hint">{t('loading')}</p>
  if (error || !draft) return <p className="hint">{error?.message ?? t('notFound')}</p>

  const provenance = draft.provenance as Record<string, string | null>
  const decide = (decision: 'approved' | 'rejected') =>
    review.mutate(
      { decision, comment },
      {
        onSuccess: () =>
          toast.success(t(decision === 'approved' ? 'approvedToast' : 'rejectedToast')),
        onError: (e: Error) => toast.error(e.message),
      },
    )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div className="page-head">
        <div>
          <h1 className="page-title">{t('title', { repo: draft.target_repo ?? '' })}</h1>
          <p className="page-sub">
            {t('summary', {
              rows: draft.rows,
              source: draft.source_rows,
              columns: draft.schema.length,
            })}
          </p>
          <p className="hint">
            {t('provenance', {
              connector: provenance.connector ?? '—',
              fetched: provenance.fetched_at ?? '—',
              licence: provenance.licence ?? t('noLicence'),
            })}
          </p>
        </div>
        {draft.recipe_id && (
          <Link className="btn btn-outline" href={`/recipes/${draft.recipe_id}`}>
            {t('editRecipe')}
          </Link>
        )}
      </div>

      {(draft.warnings ?? []).length > 0 && (
        <div className="card" role="alert">
          <div className="card-body">
            <ul>
              {(draft.warnings ?? []).map((w) => (
                <li key={w}>
                  <span className="badge badge-warning">{t('warning')}</span> {w}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <nav className="tabs hub-tabs" aria-label={t('sections')}>
        {TABS.map((key) => (
          <button
            key={key}
            type="button"
            className={cn('tab', tab === key && 'active')}
            aria-current={tab === key ? 'page' : undefined}
            onClick={() => setTab(key)}
          >
            {t(`tabs.${key}`)}
          </button>
        ))}
      </nav>

      <div className="card">
        <div className="card-body">
          {tab === 'schema' && <SchemaTab draft={draft} />}
          {tab === 'sample' && <SampleTab draft={draft} />}
          {tab === 'quality' && <QualityTab draft={draft} />}
          {tab === 'changes' && <ChangesTab draft={draft} />}
        </div>
      </div>

      <div className="card">
        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {draft.published_url && (
            <p>
              <a
                className="underline"
                href={draft.published_url}
                target="_blank"
                rel="noreferrer noopener"
              >
                {t('publishedAt', { url: draft.published_url })}
              </a>
              {draft.kind === 'corpus' && draft.target_repo && (
                <>
                  {' · '}
                  <Link
                    className="underline"
                    href={`/collections?${new URLSearchParams({
                      repo: draft.target_repo,
                      text: 'text',
                      query: 'title',
                    })}`}
                  >
                    {t('createCollection')}
                  </Link>
                </>
              )}
            </p>
          )}
          {draft.review && (
            <p className="hint">
              {t('lastReview', {
                decision: t(
                  `decision.${draft.review.decision === 'approved' ? 'approved' : 'rejected'}`,
                ),
                comment: draft.review.comment ?? '',
              })}
            </p>
          )}
          {!state.canApprove && state.reasons.length > 0 && draft.status === 'succeeded' && (
            <div role="alert">
              <p className="hint">{t('blocked')}</p>
              <ul>
                {state.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
          <label className="label" htmlFor="review-comment">
            {t('comment')}
          </label>
          <textarea
            id="review-comment"
            className="input"
            rows={2}
            maxLength={2000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            disabled={!state.canReject || review.isPending}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!state.canApprove || review.isPending}
              onClick={() => decide('approved')}
            >
              {t('approve')}
            </button>
            <button
              type="button"
              className="btn btn-outline"
              disabled={!state.canReject || review.isPending}
              onClick={() => decide('rejected')}
            >
              {t('reject')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
