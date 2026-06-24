import { Icon } from '@/components/app/icon'

type Source = {
  host: string
  type: string
  icon: string
  pages: number
  datasets: number
  lastCrawl: string
  frequency: string
  status: string
  variant: 'success' | 'info' | 'warning' | 'destructive'
}

const SOURCES: Source[] = [
  { host: 'docs.example.com', type: 'sitemap', icon: 'globe', pages: 128, datasets: 3, lastCrawl: '12 min ago', frequency: 'Daily', status: 'OK', variant: 'success' },
  { host: 'help.acme.io', type: 'site', icon: 'globe', pages: 210, datasets: 1, lastCrawl: 'in progress', frequency: 'Manual', status: 'Crawling', variant: 'info' },
  { host: 'api.acme.io', type: 'site', icon: 'globe', pages: 86, datasets: 1, lastCrawl: 'yesterday', frequency: 'Weekly', status: 'OK', variant: 'success' },
  { host: 'blog.example.com/feed', type: 'rss', icon: 'rss', pages: 42, datasets: 2, lastCrawl: '1d ago', frequency: '6h', status: 'OK', variant: 'success' },
  { host: 'handbook.firma.de', type: 'sitemap', icon: 'workflow', pages: 164, datasets: 1, lastCrawl: '2d ago', frequency: 'Weekly', status: 'OK', variant: 'success' },
  { host: 'boe.es', type: 'sitemap', icon: 'workflow', pages: 512, datasets: 1, lastCrawl: '1d ago', frequency: 'Monthly', status: 'OK', variant: 'success' },
  { host: 'changelog.acme.io/rss', type: 'rss', icon: 'rss', pages: 38, datasets: 1, lastCrawl: '3h ago', frequency: '12h', status: 'OK', variant: 'success' },
  { host: 'legacy.kb.example', type: 'site', icon: 'globe', pages: 0, datasets: 0, lastCrawl: '4d ago', frequency: '—', status: 'Error 403', variant: 'destructive' },
  { host: 'intranet.firma.de', type: 'site', icon: 'globe', pages: 0, datasets: 0, lastCrawl: '5d ago', frequency: '—', status: 'Auth required', variant: 'warning' },
]

const STATS = [
  { label: 'Active sources', icon: 'globe', value: '11', sub: '9 sites · 2 RSS', tone: 'muted' },
  { label: 'Indexed pages', icon: 'fileText', value: '3,420', sub: 'last crawl 12 min ago', tone: 'muted' },
  { label: 'Scraped tokens', icon: 'cpu', value: '8.4M', sub: 'after cleaning: 2.1M', tone: 'muted' },
  { label: 'Failures', icon: 'alert', value: '2', sub: 'to reconnect', tone: 'down' },
]

export default function SourcesPage() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Sources</h1>
          <p className="page-sub">
            Reusable content origins for your generations. 11 connected sources.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-primary">
            <Icon name="plus" />
            Add a source
          </button>
        </div>
      </div>

      <div className="stat-grid" style={{ marginBottom: 18 }}>
        {STATS.map((s) => (
          <div className="card stat" key={s.label}>
            <div className="stat-top">
              <span className="stat-label">{s.label}</span>
              <span className="stat-ic">
                <Icon name={s.icon} />
              </span>
            </div>
            <div className="stat-val">{s.value}</div>
            <div className={`stat-delta ${s.tone}`}>{s.sub}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <div className="card-title">All sources</div>
          </div>
          <label className="topbar-search" style={{ display: 'flex', minWidth: 240 }}>
            <Icon name="search" />
            <input placeholder="Filter…" />
          </label>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Type</th>
              <th>Pages</th>
              <th>Linked datasets</th>
              <th>Last crawl</th>
              <th>Frequency</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {SOURCES.map((s) => (
              <tr key={s.host} style={{ cursor: 'pointer' }}>
                <td>
                  <div className="cell-main">
                    <span className="cell-ic">
                      <Icon name={s.icon} />
                    </span>
                    <div className="cell-title">{s.host}</div>
                  </div>
                </td>
                <td>
                  <span className="tag">{s.type}</span>
                </td>
                <td className="mono">{s.pages || '—'}</td>
                <td className="mono muted">{s.datasets || '—'}</td>
                <td className="muted">{s.lastCrawl}</td>
                <td className="muted">{s.frequency}</td>
                <td>
                  <span className={`badge badge-${s.variant}`}>
                    {(s.variant === 'info' || s.variant === 'success') && (
                      <span className="dot" />
                    )}
                    {s.status}
                  </span>
                </td>
                <td>
                  <button className="icon-btn">
                    <Icon name="more" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
