'use client'

import { useTranslations } from 'next-intl'
import { useAdminUsage } from '@/hooks/use-admin'

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card">
      <div className="card-body">
        <div className="hint">{label}</div>
        <div style={{ fontSize: 26, fontWeight: 600, marginTop: 4 }}>{value}</div>
      </div>
    </div>
  )
}

export default function AdminOverviewPage() {
  const { data, error } = useAdminUsage()
  const t = useTranslations('admin.overview')
  const tc = useTranslations('common')
  if (error) return <p className="hint">{error.message}</p>
  if (!data) return <p className="muted">{tc('loading')}</p>
  const runs = Object.entries(data.runs_30d)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
          gap: 12,
        }}
      >
        <Stat label={t('accounts')} value={data.users.total} />
        <Stat label={t('active')} value={data.users.active} />
        <Stat label={t('admins')} value={data.users.admins} />
        <Stat label={t('signedIn')} value={data.users.signed_in_30d} />
        <Stat label={t('datasets')} value={data.datasets} />
        <Stat label={t('pairs')} value={data.pairs} />
        <Stat label={t('running')} value={data.running} />
      </div>
      <div className="card">
        <div className="card-head">
          <div className="card-title">{t('runsTitle')}</div>
        </div>
        <div className="card-body">
          {runs.length === 0 ? (
            <span className="muted">{t('noRuns')}</span>
          ) : (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {runs.map(([status, count]) => (
                <span key={status} className="tag">
                  {status} · {count}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
