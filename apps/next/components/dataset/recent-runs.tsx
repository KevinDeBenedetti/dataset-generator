'use client'

import Link from 'next/link'
import { useLocale, useTranslations } from 'next-intl'
import { Icon } from '@/components/app/icon'
import { useAllDatasetRuns } from '@/hooks'

function formatDate(value: string | null | undefined, locale: string): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString(locale)
}

// Every recorded generation run, newest first — one row per run.
export function RecentRuns() {
  const t = useTranslations('generate.runs')
  const tc = useTranslations('common')
  const locale = useLocale()
  const runsQuery = useAllDatasetRuns()
  const runs = runsQuery.data ?? []

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{t('title')}</div>
          <div className="card-desc">{t('description')}</div>
        </div>
        <button
          className="btn btn-outline btn-sm"
          onClick={() => runsQuery.refetch()}
          disabled={runsQuery.isRefetching}
          type="button"
        >
          <Icon name="refresh" className={runsQuery.isRefetching ? 'animate-spin' : undefined} />
          {tc('refresh')}
        </button>
      </div>
      {runsQuery.isPending && (
        <div className="card-body">
          <p className="muted">{t('loading')}</p>
        </div>
      )}
      {!runsQuery.isPending && runsQuery.error && (
        <div className="card-body">
          <p className="hint" style={{ color: 'var(--destructive)' }}>
            {runsQuery.error instanceof Error ? runsQuery.error.message : t('loadFailed')}
          </p>
        </div>
      )}
      {!runsQuery.isPending && !runsQuery.error && runs.length === 0 && (
        <div className="card-body">
          <p className="muted">{t('empty')}</p>
        </div>
      )}
      {runs.length > 0 && (
        <table className="table stack-table">
          <thead>
            <tr>
              <th>{t('dataset')}</th>
              <th>{t('version')}</th>
              <th>{t('pairs')}</th>
              <th>{t('source')}</th>
              <th>{t('started')}</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={`${run.dataset}-${run.run_name ?? run.version}`}>
                <td data-label={t('dataset')}>
                  <Link href={`/drafts/${encodeURIComponent(run.dataset)}`} className="cell-title">
                    {run.dataset}
                  </Link>
                </td>
                <td data-label={t('version')}>
                  <span className="tag">
                    {run.run_name ?? (run.version != null ? `v${run.version}` : '—')}
                  </span>
                </td>
                <td className="muted" data-label={t('pairs')}>
                  {run.item_count ?? '—'}
                </td>
                {/* Cut to one line on wide screens (full URL on hover); the
                    stacked phone layout shows it whole. */}
                <td
                  className="muted run-source"
                  title={run.source_url ?? undefined}
                  data-label={t('source')}
                >
                  {run.source_url ?? '—'}
                </td>
                <td className="muted" data-label={t('started')}>
                  {formatDate(run.created_at, locale)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
