import { Icon } from '@/components/app/icon'
import './exports.css'

type Format = {
  id: string
  icon: string
  name: string
  ext: string
  desc: string
  selected?: boolean
}

const FORMATS: Format[] = [
  {
    id: 'langfuse',
    icon: 'zap',
    name: 'Langfuse',
    ext: 'API',
    desc: 'Push the dataset directly into a Langfuse project for training management.',
    selected: true,
  },
  {
    id: 'jsonl',
    icon: 'fileJson',
    name: 'JSONL',
    ext: '.jsonl',
    desc: 'One Q/A pair per line. Ideal for fine-tuning.',
  },
  {
    id: 'json',
    icon: 'fileJson',
    name: 'JSON',
    ext: '.json',
    desc: 'Structured array with metadata and sources.',
  },
  {
    id: 'csv',
    icon: 'table',
    name: 'CSV',
    ext: '.csv',
    desc: 'Tabular for analysis and human review.',
  },
]

type ExportRow = {
  dataset: string
  format: string
  pairs: string
  date: string
  status: string
  variant: 'success' | 'destructive'
}

const RECENT: ExportRow[] = [
  {
    dataset: 'docs-fr',
    format: 'langfuse',
    pairs: '1,190',
    date: '12 min ago',
    status: 'Succeeded',
    variant: 'success',
  },
  {
    dataset: 'api-reference-en',
    format: 'jsonl',
    pairs: '1,730',
    date: 'yesterday',
    status: 'Succeeded',
    variant: 'success',
  },
  {
    dataset: 'legal-es',
    format: 'csv',
    pairs: '958',
    date: '2d ago',
    status: 'Succeeded',
    variant: 'success',
  },
  {
    dataset: 'faq-produit-de',
    format: 'langfuse',
    pairs: '—',
    date: '3d ago',
    status: 'Auth failed',
    variant: 'destructive',
  },
]

export default function ExportsPage() {
  return (
    <div className="exports-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Exports</h1>
          <p className="page-sub">
            Ship your datasets to Langfuse, JSON, CSV or JSONL. Configure then export in one click.
          </p>
        </div>
      </div>

      <div className="grid-2" style={{ alignItems: 'start', gap: '24px' }}>
        {/* Left: config */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">1 · Dataset</div>
              </div>
            </div>
            <div className="card-body" style={{ paddingTop: 0 }}>
              <select className="select" defaultValue="docs-fr · v4 · 1,284 pairs">
                <option>docs-fr · v4 · 1,284 pairs</option>
                <option>support-en · v7 · 2,047 pairs</option>
                <option>legal-es · v3 · 958 pairs</option>
              </select>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">2 · Format</div>
              </div>
            </div>
            <div className="card-body" style={{ paddingTop: 0 }}>
              <div className="grid-2" style={{ gap: '12px' }}>
                {FORMATS.map((f) => (
                  <div key={f.id} className={`card fmt-card${f.selected ? ' sel' : ''}`}>
                    <div className="fh">
                      <span className="fi">
                        <Icon name={f.icon} />
                      </span>
                      <div>
                        <h4>{f.name}</h4>
                        <span className="ext">{f.ext}</span>
                      </div>
                    </div>
                    <p>{f.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">3 · Options</div>
              </div>
            </div>
            <div
              className="card-body"
              style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: '14px' }}
            >
              <div className="field">
                <label htmlFor="export-langfuse-project" className="label">
                  Langfuse project
                </label>
                <select
                  id="export-langfuse-project"
                  className="select"
                  defaultValue="prod · training-data"
                >
                  <option>prod · training-data</option>
                  <option>staging · eval</option>
                </select>
              </div>
              <div
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
              >
                <div>
                  <div className="label">Include metadata</div>
                  <div className="hint">Source, quality score, version.</div>
                </div>
                <span className="switch on" />
              </div>
              <div
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
              >
                <div>
                  <div className="label">Exclude pairs &lt; 0.80</div>
                  <div className="hint">Filters out low scores.</div>
                </div>
                <span className="switch on" />
              </div>
              <div
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
              >
                <div>
                  <div className="label">Anonymize source URLs</div>
                </div>
                <span className="switch" />
              </div>
            </div>
            <div className="card-foot">
              <span className="muted" style={{ fontSize: '12.5px' }}>
                1,190 pairs will be exported (94 excluded)
              </span>
              <div style={{ flex: 1 }} />
              <button className="btn btn-primary">
                <Icon name="upload" />
                Export to Langfuse
              </button>
            </div>
          </div>
        </div>

        {/* Right: preview + history */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">Output preview</div>
                <div className="card-desc">langfuse · push payload</div>
              </div>
              <button className="btn btn-ghost btn-sm">
                <Icon name="copy" />
                Copy
              </button>
            </div>
            <div className="card-body" style={{ paddingTop: 0 }}>
              <div className="codeblock">
                {'POST /api/public/datasets/items\n{\n  '}
                <span className="k">{'"datasetName"'}</span>
                {': '}
                <span className="s">{'"docs-fr"'}</span>
                {',\n  '}
                <span className="k">{'"input"'}</span>
                {':  '}
                <span className="s">{'"How do I configure the API key?"'}</span>
                {',\n  '}
                <span className="k">{'"expectedOutput"'}</span>
                {': '}
                <span className="s">{'"Copy .env.example to .env…"'}</span>
                {',\n  '}
                <span className="k">{'"metadata"'}</span>
                {': {\n    '}
                <span className="k">{'"source"'}</span>
                {': '}
                <span className="s">{'"docs.example.com/api/auth"'}</span>
                {',\n    '}
                <span className="k">{'"quality"'}</span>
                {': '}
                <span className="n">0.97</span>
                {', '}
                <span className="k">{'"lang"'}</span>
                {': '}
                <span className="s">{'"fr"'}</span>
                {'\n  }\n}'}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">Recent exports</div>
              </div>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Format</th>
                  <th>Pairs</th>
                  <th>Date</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {RECENT.map((r) => (
                  <tr key={r.dataset}>
                    <td className="cell-title">{r.dataset}</td>
                    <td>
                      <span className="tag">{r.format}</span>
                    </td>
                    <td className="mono">{r.pairs}</td>
                    <td className="muted">{r.date}</td>
                    <td>
                      <span className={`badge badge-${r.variant}`}>
                        <span className="dot" />
                        {r.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
