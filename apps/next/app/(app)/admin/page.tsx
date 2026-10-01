'use client'

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
  if (error) return <p className="hint">{error.message}</p>
  if (!data) return <p className="muted">Loading…</p>
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
        <Stat label="Accounts" value={data.users.total} />
        <Stat label="Active" value={data.users.active} />
        <Stat label="Admins" value={data.users.admins} />
        <Stat label="Signed in (30 days)" value={data.users.signed_in_30d} />
        <Stat label="Datasets" value={data.datasets} />
        <Stat label="Q&A pairs" value={data.pairs} />
        <Stat label="Runs in progress" value={data.running} />
      </div>
      <div className="card">
        <div className="card-head">
          <div className="card-title">Job runs, last 30 days</div>
        </div>
        <div className="card-body">
          {runs.length === 0 ? (
            <span className="muted">No runs.</span>
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
