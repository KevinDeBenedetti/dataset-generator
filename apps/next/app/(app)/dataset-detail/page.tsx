import Link from 'next/link'
import { Icon } from '@/components/app/icon'
import './dataset-detail.css'

type Qa = {
  q: string
  a: string
  source: string
  score: number
  duplicate: boolean
}

const QA: Qa[] = [
  {
    q: 'How do I configure the OpenAI API key?',
    a: 'Copy the <code>.env.example</code> file to <code>.env</code> at the root of the project, then set your key in the <code>OPENAI_API_KEY</code> variable before running <code>make start</code>.',
    source: 'docs.example.com/api/auth',
    score: 0.97,
    duplicate: false,
  },
  {
    q: 'Which languages are supported for generation?',
    a: 'DatasetGen generates datasets in French (fr), English (en), Spanish (es) and German (de), with localized prompts for each language.',
    source: 'docs.example.com/languages',
    score: 0.96,
    duplicate: false,
  },
  {
    q: 'How does duplicate detection work?',
    a: 'Pairs are compared by semantic similarity (cosine). Above the configured threshold (0.92 by default), the redundant pair is discarded before being added to the dataset.',
    source: 'docs.example.com/dedup',
    score: 0.88,
    duplicate: true,
  },
  {
    q: 'Which formats can a dataset be exported to?',
    a: 'Datasets can be exported to Langfuse, JSON, JSONL and CSV. The export system is extensible for custom formats.',
    source: 'docs.example.com/export',
    score: 0.95,
    duplicate: false,
  },
]

export default function DatasetDetailPage() {
  return (
    <div className="dd-page">
      <Link
        href="/datasets"
        className="btn btn-ghost btn-sm"
        style={{ margin: '-4px 0 14px', paddingLeft: 6 }}
      >
        <Icon name="chevronLeft" />
        Datasets
      </Link>

      <div className="page-head">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="cell-ic ic-lg" style={{ width: 42, height: 42, borderRadius: 10 }}>
              <Icon name="database" className="ic-lg" />
            </span>
            <div>
              <h1 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                docs-fr <span className="tag">v4</span>
              </h1>
              <p className="page-sub" style={{ marginTop: 3 }}>
                1,284 Q/A pairs · language FR · 2 sources · quality{' '}
                <b style={{ color: 'var(--success)' }}>94%</b>
              </p>
            </div>
          </div>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline">
            <Icon name="play" />
            Rerun
          </button>
          <button className="btn btn-outline">
            <Icon name="download" />
            Export
          </button>
          <button className="btn btn-primary">
            <Icon name="plus" />
            Add Q/A
          </button>
        </div>
      </div>

      <div className="tabs" style={{ marginBottom: 20 }}>
        <button className="tab active" data-tab="pairs">
          Q/A pairs{' '}
          <span className="muted" style={{ fontFamily: "'Geist Mono', monospace" }}>
            1284
          </span>
        </button>
        <button className="tab" data-tab="versions">
          Versions
        </button>
        <button className="tab" data-tab="clean">
          Cleanup
        </button>
        <button className="tab" data-tab="sources">
          Sources
        </button>
        <button className="tab" data-tab="settings">
          Settings
        </button>
      </div>

      {/* PAIRS */}
      <div className="tabpane active" id="pairs">
        <div
          className="toolbar"
          style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center' }}
        >
          <label className="topbar-search" style={{ display: 'flex', minWidth: 260 }}>
            <Icon name="search" />
            <input placeholder="Search within pairs…" />
          </label>
          <div style={{ flex: 1 }} />
          <span className="badge badge-outline">3 duplicates flagged</span>
          <button className="btn btn-outline btn-sm">
            <Icon name="filter" />
            Quality
          </button>
        </div>

        {/* Add Q/A inline */}
        <div className="card" id="addqa" style={{ marginBottom: 18, borderStyle: 'dashed' }}>
          <div className="card-head" style={{ paddingBottom: 12 }}>
            <div>
              <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Icon name="plus" />
                Add a Q/A pair
              </div>
              <div className="card-desc">
                Manual entry or LLM-assisted generation from the source.
              </div>
            </div>
          </div>
          <div
            className="card-body"
            style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: 12 }}
          >
            <div className="field">
              <label htmlFor="qa-question" className="label">
                Question
              </label>
              <input
                id="qa-question"
                className="input"
                placeholder="How do I configure the API key?"
              />
            </div>
            <div className="field">
              <label htmlFor="qa-answer" className="label">
                Answer
              </label>
              <textarea
                id="qa-answer"
                className="textarea"
                rows={3}
                placeholder="Copy the .env.example file to .env then set your key…"
              />
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                flexWrap: 'wrap',
              }}
            >
              <select
                className="select"
                style={{ width: 'auto' }}
                defaultValue="Source: docs.example.com"
              >
                <option>Source: docs.example.com</option>
                <option>Source: sitemap</option>
                <option>No source</option>
              </select>
              <div style={{ flex: 1 }} />
              <button className="btn btn-outline">
                <Icon name="sparkles" />
                Generate with LLM
              </button>
              <button className="btn btn-primary">
                <Icon name="check" />
                Add to dataset
              </button>
            </div>
          </div>
        </div>

        <div id="qalist">
          {QA.map((q, i) => (
            <div className="qa" key={q.q}>
              <div className="qa-q">
                <span className="qmark">Q{i + 1}</span>
                <span>{q.q}</span>
              </div>
              <div className="qa-a" dangerouslySetInnerHTML={{ __html: q.a }} />
              <div className="qa-meta">
                <span className="tag">{q.source}</span>
                <span className={`badge badge-${q.score >= 0.92 ? 'success' : 'warning'}`}>
                  <span className="dot" />
                  score {q.score.toFixed(2)}
                </span>
                {q.duplicate && (
                  <span className="badge badge-warning">
                    <Icon name="copyCheck" className="ic-sm" />
                    possible duplicate
                  </span>
                )}
                <div style={{ flex: 1 }} />
                <div className="qa-actions">
                  <button className="icon-btn" title="Edit">
                    <Icon name="edit" />
                  </button>
                  <button className="icon-btn" title="Regenerate">
                    <Icon name="sparkles" />
                  </button>
                  <button className="icon-btn" title="Delete">
                    <Icon name="trash" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 8 }}>
          <button className="btn btn-outline btn-sm">
            <Icon name="chevronDown" />
            Load 50 more pairs
          </button>
        </div>
      </div>

      {/* VERSIONS */}
      <div className="tabpane" id="versions">
        <div className="card">
          <div className="card-body" style={{ paddingTop: 20 }}>
            <div className="ver cur">
              <span className="vdot">
                <Icon name="gitBranch" />
              </span>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                  <b>v4</b>
                  <span className="badge badge-success">
                    <span className="dot" />
                    Current
                  </span>
                  <span className="muted" style={{ fontSize: 12 }}>
                    12 min ago
                  </span>
                </div>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  +47 pairs from Langfuse · 3 duplicates removed · quality 94%
                </div>
              </div>
            </div>
            <div className="ver">
              <span className="vdot">
                <Icon name="gitBranch" />
              </span>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                  <b>v3</b>
                  <span className="muted" style={{ fontSize: 12 }}>
                    2 days ago
                  </span>
                </div>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  Regeneration on new prompt v2 · quality 93%
                </div>
              </div>
            </div>
            <div className="ver">
              <span className="vdot">
                <Icon name="gitBranch" />
              </span>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                  <b>v2</b>
                  <span className="muted" style={{ fontSize: 12 }}>
                    6 days ago
                  </span>
                </div>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  Added sitemap source · +320 pairs
                </div>
              </div>
            </div>
            <div className="ver">
              <span className="vdot">
                <Icon name="sparkles" />
              </span>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                  <b>v1</b>
                  <span className="muted" style={{ fontSize: 12 }}>
                    9 days ago
                  </span>
                </div>
                <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                  Initial creation · 917 pairs · docs.example.com
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* CLEAN before/after */}
      <div className="tabpane" id="clean">
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Before / after cleanup comparison</div>
              <div className="card-desc">
                Source page <span className="tag">docs.example.com/api/auth</span> · 4,820 → 1,190
                tokens kept
              </div>
            </div>
            <div className="tabs">
              <button className="tab active">Diff</button>
              <button className="tab">Raw</button>
            </div>
          </div>
          <div className="card-body">
            <div className="diff">
              <div className="col">
                <h4>
                  <Icon name="fileText" className="ic-sm" />
                  Before — raw scraped HTML
                </h4>
                <pre>
                  <span className="del">
                    {'<nav class="site-header">…menu, cookies, ads…</nav>'}
                  </span>
                  {'\n'}
                  {'<h1>API Authentication</h1>\n'}
                  {'To authenticate, copy the file\n'}
                  <span className="del">{'<span class="ad-slot">Sponsored</span>'}</span>
                  {'\n.env.example to .env and set\n'}
                  {'your OPENAI_API_KEY.\n'}
                  <span className="del">{'<footer>© 2026 · Legal · Follow us…</footer>'}</span>
                  {'\n'}
                  <span className="del">{'[ 312 lines of scripts / styles ]'}</span>
                </pre>
              </div>
              <div className="col">
                <h4>
                  <Icon name="check" className="ic-sm" />
                  After — normalized text
                </h4>
                <pre>
                  {'## API Authentication\n\n'}
                  {'To authenticate, copy the file\n'}
                  <span className="add">{'`.env.example`'}</span>
                  {' to '}
                  <span className="add">{'`.env`'}</span>
                  {' and set\n'}
                  {'your '}
                  <span className="add">{'`OPENAI_API_KEY`'}</span>
                  {'.\n\n'}
                  <span className="add">{'→ 1 Q/A pair generated from this block'}</span>
                </pre>
              </div>
            </div>
          </div>
          <div className="card-foot">
            <span className="muted" style={{ fontSize: 12.5 }}>
              Applied rules: remove nav/footer/ads · whitespace deduplication · markdownification
            </span>
            <div style={{ flex: 1 }} />
            <button className="btn btn-ghost btn-sm">
              <Icon name="settings" />
              Configure cleanup
            </button>
          </div>
        </div>
      </div>

      {/* SOURCES */}
      <div className="tabpane" id="sources">
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Type</th>
                <th>Pages</th>
                <th>Pairs</th>
                <th>Last scrape</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                {/* oxlint-disable-next-line jsx-a11y/control-has-associated-label --
                    false positive: static, non-interactive cell; the icon is
                    already aria-hidden (see Icon) and the cell has visible
                    accessible text (docs.example.com). */}
                <td>
                  <div className="cell-main">
                    <span className="cell-ic">
                      <Icon name="globe" />
                    </span>
                    <div className="cell-title">docs.example.com</div>
                  </div>
                </td>
                <td>
                  <span className="tag">sitemap</span>
                </td>
                <td className="mono">128</td>
                <td className="mono">964</td>
                <td className="muted">12 min ago</td>
                <td>
                  <span className="badge badge-success">
                    <span className="dot" />
                    OK
                  </span>
                </td>
              </tr>
              <tr>
                {/* oxlint-disable-next-line jsx-a11y/control-has-associated-label --
                    same false positive as above: static cell, icon already
                    aria-hidden, cell has visible accessible text. */}
                <td>
                  <div className="cell-main">
                    <span className="cell-ic">
                      <Icon name="rss" />
                    </span>
                    <div className="cell-title">blog.example.com/feed</div>
                  </div>
                </td>
                <td>
                  <span className="tag">rss</span>
                </td>
                <td className="mono">42</td>
                <td className="mono">320</td>
                <td className="muted">1 day ago</td>
                <td>
                  <span className="badge badge-success">
                    <span className="dot" />
                    OK
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* SETTINGS */}
      <div className="tabpane" id="settings">
        <div className="grid-2">
          <div className="card">
            <div className="card-head">
              <div className="card-title">Generation</div>
            </div>
            <div
              className="card-body"
              style={{ display: 'flex', flexDirection: 'column', gap: 14 }}
            >
              <div className="field">
                <label htmlFor="detail-llm-model" className="label">
                  LLM model
                </label>
                <select id="detail-llm-model" className="select" defaultValue="gpt-4o-mini">
                  <option>gpt-4o-mini</option>
                  <option>gpt-4o</option>
                  <option>claude-3.5-sonnet</option>
                  <option>mistral-large</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="detail-prompt" className="label">
                  Prompt
                </label>
                <select id="detail-prompt" className="select" defaultValue="qa-fr · v2">
                  <option>qa-fr · v2</option>
                  <option>qa-fr · v1</option>
                </select>
              </div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div>
                  <div className="label">Duplicate detection</div>
                  <div className="hint">Cosine threshold ≥ 0.92</div>
                </div>
                <span className="switch on" />
              </div>
            </div>
          </div>
          <div className="card">
            <div className="card-head">
              <div className="card-title">Danger zone</div>
            </div>
            <div
              className="card-body"
              style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                }}
              >
                <div>
                  <div className="label">Clear the dataset</div>
                  <div className="hint">Removes all pairs, keeps the config.</div>
                </div>
                <button className="btn btn-outline btn-sm">Clear</button>
              </div>
              <hr className="sep" />
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                }}
              >
                <div>
                  <div className="label" style={{ color: 'var(--destructive)' }}>
                    Delete the dataset
                  </div>
                  <div className="hint">Irreversible action.</div>
                </div>
                <button className="btn btn-destructive btn-sm">
                  <Icon name="trash" />
                  Delete
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
