import './quality.css'
import { Icon } from '@/components/app/icon'

type Duplicate = {
  id: number
  cosine: string
  source: string
  pct: string
  keep: { q: string; a: string; score: string }
  remove: { q: string; a: string; score: string }
}

const DUPLICATES: Duplicate[] = [
  {
    id: 1,
    cosine: 'cosine 0.96',
    source: 'docs.example.com/api/auth · /quickstart',
    pct: '96%',
    keep: {
      q: 'How do I configure the OpenAI API key?',
      a: 'Copy the .env.example file to .env, then fill in OPENAI_API_KEY.',
      score: 'keep · 0.97',
    },
    remove: {
      q: 'Where do I put my API key?',
      a: 'Fill in the OPENAI_API_KEY in the root .env file.',
      score: 'remove · 0.91',
    },
  },
  {
    id: 2,
    cosine: 'cosine 0.93',
    source: 'docs.example.com/export',
    pct: '93%',
    keep: {
      q: 'Which export formats are available?',
      a: 'Langfuse, JSON, JSONL and CSV, with an extensible system.',
      score: 'keep · 0.95',
    },
    remove: {
      q: 'What can you export to?',
      a: 'You can export to JSON, CSV, JSONL and Langfuse.',
      score: 'remove · 0.90',
    },
  },
]

export default function QualityPage() {
  return (
    <div className="quality-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Quality control</h1>
          <p className="page-sub">Detected duplicates, score distribution and pairs below the threshold — per dataset.</p>
        </div>
        <div className="page-actions">
          <select className="select" style={{ width: 'auto' }} defaultValue="docs-fr · v4">
            <option>docs-fr · v4</option>
            <option>support-en · v7</option>
            <option>All datasets</option>
          </select>
          <button className="btn btn-primary"><Icon name="play" />Re-run analysis</button>
        </div>
      </div>

      <div className="stat-grid" style={{ marginBottom: 18 }}>
        <div className="card stat">
          <div className="stat-top"><span className="stat-label">Average score</span><span className="stat-ic"><Icon name="shield" /></span></div>
          <div className="stat-val">0.94</div>
          <div className="stat-delta up"><Icon name="arrowUpRight" className="ic-sm" />+0.02</div>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="stat-label">Duplicates</span><span className="stat-ic"><Icon name="copyCheck" /></span></div>
          <div className="stat-val">12</div>
          <div className="stat-delta muted">to arbitrate</div>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="stat-label">Below 0.80 threshold</span><span className="stat-ic"><Icon name="alert" /></span></div>
          <div className="stat-val">31</div>
          <div className="stat-delta muted">2.4% of the dataset</div>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="stat-label">Validated</span><span className="stat-ic"><Icon name="check" /></span></div>
          <div className="stat-val">1,241</div>
          <div className="stat-delta muted">96.6%</div>
        </div>
      </div>

      <div className="grid-2" style={{ marginBottom: 18 }}>
        <div className="card">
          <div className="card-head"><div><div className="card-title">Score distribution</div></div></div>
          <div className="card-body" style={{ paddingTop: 6 }}>
            <div className="bar-row"><span className="bl">0.9–1.0</span><div className="progress" style={{ flex: 1 }}><span style={{ width: '72%' }} /></div><span className="bv">924</span></div>
            <div className="bar-row"><span className="bl">0.8–0.9</span><div className="progress" style={{ flex: 1 }}><span style={{ width: '24%' }} /></div><span className="bv">317</span></div>
            <div className="bar-row"><span className="bl">0.7–0.8</span><div className="progress" style={{ flex: 1 }}><span style={{ width: '5%', background: 'var(--warning)' }} /></div><span className="bv">28</span></div>
            <div className="bar-row"><span className="bl">&lt; 0.7</span><div className="progress" style={{ flex: 1 }}><span style={{ width: '2%', background: 'var(--destructive)' }} /></div><span className="bv">15</span></div>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><div><div className="card-title">Quality rules</div></div><button className="btn btn-ghost btn-sm"><Icon name="settings" />Configure</button></div>
          <div className="card-body" style={{ paddingTop: 2, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}><div><div className="label">Duplicate threshold</div><div className="hint">Cosine similarity</div></div><span className="tag">≥ 0.92</span></div>
            <hr className="sep" />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}><div><div className="label">Quality rejection threshold</div><div className="hint">Minimum score kept</div></div><span className="tag">0.80</span></div>
            <hr className="sep" />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}><div><div className="label">Min. answer length</div></div><span className="tag">12 words</span></div>
            <hr className="sep" />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}><div><div className="label">Automatic rejection</div><div className="hint">Applied at generation</div></div><span className="switch on" /></div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Icon name="copyCheck" />Duplicates to arbitrate</div>
            <div className="card-desc">Semantically close pairs detected in docs-fr.</div>
          </div>
          <div className="tabs"><button className="tab active">To handle <span className="muted">12</span></button><button className="tab">Resolved</button></div>
        </div>
        <div className="card-body">

          {DUPLICATES.map((d) => (
            <div className="dup" key={d.id}>
              <div className="dup-head">
                <span className="ic"><Icon name="copyCheck" /></span>
                <b style={{ fontSize: 13 }}>Duplicate #{d.id}</b>
                <span className="badge badge-warning">{d.cosine}</span>
                <div style={{ flex: 1 }} />
                <span className="muted" style={{ fontSize: 12 }}>{d.source}</span>
              </div>
              <div className="dup-pair">
                <div className="dup-side keep">
                  <div className="q">{d.keep.q}</div>
                  <div className="a">{d.keep.a}</div>
                  <span className="badge badge-success" style={{ marginTop: 10 }}><span className="dot" />{d.keep.score}</span>
                </div>
                <div className="dup-mid"><span className="pct">{d.pct}</span><span className="muted" style={{ fontSize: 10 }}>similar</span></div>
                <div className="dup-side">
                  <div className="q">{d.remove.q}</div>
                  <div className="a">{d.remove.a}</div>
                  <span className="badge badge-outline" style={{ marginTop: 10 }}>{d.remove.score}</span>
                </div>
              </div>
              <div className="dup-foot">
                <button className="btn btn-ghost btn-sm">Keep both</button>
                <button className="btn btn-outline btn-sm"><Icon name="merge" />Merge</button>
                <button className="btn btn-primary btn-sm"><Icon name="check" />Apply</button>
              </div>
            </div>
          ))}

          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 4 }}><button className="btn btn-outline btn-sm"><Icon name="chevronDown" />View the remaining 10 duplicates</button></div>
        </div>
      </div>
    </div>
  )
}
