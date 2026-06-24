import './jobs.css'
import { Icon } from '@/components/app/icon'

type Stage = { label: string; state: 'done' | 'run' | '' }

type Job = {
  id: string
  icon: string
  title: string
  meta: string
  percent: number
  eta: string
  stages: Stage[]
}

const RUNNING_JOBS: Job[] = [
  {
    id: 'support-en',
    icon: 'globe',
    title: 'support-en · scraping',
    meta: 'help.acme.io · 210 pages · started 6 min ago',
    percent: 68,
    eta: '~3 min',
    stages: [
      { label: 'Scraping', state: 'done' },
      { label: 'Cleaning', state: 'run' },
      { label: 'Generation', state: '' },
      { label: 'Quality', state: '' },
      { label: 'Export', state: '' },
    ],
  },
  {
    id: 'faq-produit-de',
    icon: 'sparkles',
    title: 'faq-produit-de · generation',
    meta: '3 sources · gpt-4o-mini · 190 / 612 pairs',
    percent: 31,
    eta: '~9 min',
    stages: [
      { label: 'Scraping', state: 'done' },
      { label: 'Cleaning', state: 'done' },
      { label: 'Generation', state: 'run' },
      { label: 'Quality', state: '' },
      { label: 'Export', state: '' },
    ],
  },
  {
    id: 'docs-fr',
    icon: 'copyCheck',
    title: 'docs-fr · deduplication',
    meta: '1,284 pairs · cosine ≥ 0.92',
    percent: 88,
    eta: '~30 s',
    stages: [
      { label: 'Scraping', state: 'done' },
      { label: 'Cleaning', state: 'done' },
      { label: 'Generation', state: 'done' },
      { label: 'Quality', state: 'run' },
      { label: 'Export', state: '' },
    ],
  },
]

type HistoryRow = {
  id: string
  icon: string
  name: string
  tag: string
  target: string
  started: string
  duration: string
  badgeVariant: 'warning' | 'success' | 'destructive'
  status: string
}

const HISTORY_ROWS: HistoryRow[] = [
  { id: 'legal-es', icon: 'upload', name: 'legal-es · export', tag: 'langfuse', target: '958 pairs', started: '—', duration: '—', badgeVariant: 'warning', status: 'Queued' },
  { id: 'handbook-de', icon: 'sparkles', name: 'handbook-de · generation', tag: 'batch', target: '164 pages', started: '—', duration: '—', badgeVariant: 'warning', status: 'Queued' },
  { id: 'docs-fr-export', icon: 'check', name: 'docs-fr · export', tag: 'langfuse', target: '1,190 pairs', started: '12 min ago', duration: '0:42', badgeVariant: 'success', status: 'Succeeded' },
  { id: 'api-reference-en', icon: 'check', name: 'api-reference-en · generation', tag: 'full', target: '86 pages', started: 'yesterday', duration: '5:18', badgeVariant: 'success', status: 'Succeeded' },
  { id: 'faq-produit-de-export', icon: 'alert', name: 'faq-produit-de · export', tag: 'langfuse', target: '—', started: '3 d ago', duration: '0:08', badgeVariant: 'destructive', status: 'Auth failed' },
]

export default function JobsPage() {
  return (
    <div className="jobs-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Jobs &amp; batch</h1>
          <p className="page-sub">Scraping, generation and export pipelines running, queued or completed.</p>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline"><Icon name="refresh" />Refresh</button>
          <button className="btn btn-outline"><Icon name="settings" />Workers (2)</button>
        </div>
      </div>

      <div className="tabs" style={{ marginBottom: 18 }}>
        <button className="tab active">Running <span className="muted">3</span></button>
        <button className="tab">Queue <span className="muted">2</span></button>
        <button className="tab">Completed</button>
        <button className="tab">Failed <span className="muted">1</span></button>
      </div>

      {RUNNING_JOBS.map((job) => (
        <div className="job" key={job.id}>
          <div className="job-top">
            <span className="job-ic"><Icon name={job.icon} /></span>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8 }}>
                {job.title} <span className="badge badge-info"><span className="dot" />Running</span>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 2, fontFamily: "'Geist Mono',monospace" }}>{job.meta}</div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{job.percent}%</div>
              <div className="muted" style={{ fontSize: 11.5 }}>{job.eta}</div>
            </div>
            <button className="btn btn-outline btn-sm"><Icon name="pause" /></button>
          </div>
          <div className="progress" style={{ marginTop: 12 }}><span style={{ width: `${job.percent}%` }} /></div>
          <div className="job-stages">
            {job.stages.map((stage) => (
              <div className={`stage${stage.state ? ` ${stage.state}` : ''}`} key={stage.label}>{stage.label}</div>
            ))}
          </div>
        </div>
      ))}

      <div className="card" style={{ marginTop: 22 }}>
        <div className="card-head"><div><div className="card-title">Queue &amp; history</div></div></div>
        <table className="table">
          <thead><tr><th>Job</th><th>Type</th><th>Target</th><th>Started</th><th>Duration</th><th>Status</th></tr></thead>
          <tbody>
            {HISTORY_ROWS.map((row) => (
              <tr key={row.id}>
                <td><div className="cell-main"><span className="cell-ic"><Icon name={row.icon} /></span><div className="cell-title">{row.name}</div></div></td>
                <td><span className="tag">{row.tag}</span></td>
                <td className="muted">{row.target}</td>
                <td className="muted">{row.started}</td>
                <td className={row.duration === '—' ? 'muted' : 'mono'}>{row.duration}</td>
                <td><span className={`badge badge-${row.badgeVariant}`}><span className="dot" />{row.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
