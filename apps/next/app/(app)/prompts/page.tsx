import { Icon } from '@/components/app/icon'
import './prompts.css'

type PromptItem = {
  name: string
  version: string
  meta: string
  selected?: boolean
  versionBadge?: boolean
}

const prompts: PromptItem[] = [
  {
    name: 'qa-fr',
    version: 'v2',
    meta: 'fr · gpt-4o-mini · 9 datasets',
    selected: true,
    versionBadge: true,
  },
  { name: 'qa-en', version: 'v3', meta: 'en · gpt-4o · 6 datasets' },
  { name: 'qa-factuel', version: 'v1', meta: 'multi · claude-3.5 · 2 datasets' },
  { name: 'qa-de', version: 'v1', meta: 'de · gpt-4o-mini · 3 datasets' },
  { name: 'qa-es', version: 'v2', meta: 'es · mistral-large · 1 dataset' },
]

const systemPrompt = `You are a dataset generator. From the provided CONTEXT, write factual, self-contained and non-redundant question-answer pairs, in French.

Rules:
- the question must be understandable without the context;
- the answer must be faithful to the context, concise (≤ {max_words} words);
- never invent information absent from the context.`

const userInstruction = `CONTEXT:
{context}

Generate {n} Q/A pairs in JSON format: [{"question": "...", "answer": "..."}]`

export default function PromptsPage() {
  return (
    <div className="prompts-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">LLM Prompts</h1>
          <p className="page-sub">
            Versioned prompt templates for Q/A pair generation. Reusable per dataset and per
            language.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline">
            <Icon name="copy" />
            Duplicate
          </button>
          <button className="btn btn-primary">
            <Icon name="plus" />
            New prompt
          </button>
        </div>
      </div>

      <div className="pe">
        <div className="plist">
          {prompts.map((p) => (
            <div key={p.name} className={p.selected ? 'pitem sel' : 'pitem'}>
              <div className="pn">
                {p.name}{' '}
                {p.versionBadge ? (
                  <span className="badge badge-success" style={{ height: '18px' }}>
                    <span className="dot"></span>
                    {p.version}
                  </span>
                ) : (
                  <span className="tag" style={{ fontSize: '11px' }}>
                    {p.version}
                  </span>
                )}
              </div>
              <div className="pm">{p.meta}</div>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          <div className="card">
            <div className="card-head">
              <div>
                <div
                  className="card-title"
                  style={{ display: 'flex', alignItems: 'center', gap: '9px' }}
                >
                  qa-fr <span className="tag">v2</span>
                </div>
                <div className="card-desc">Modified 2 days ago · used by 9 datasets</div>
              </div>
              <div className="page-actions">
                <button className="btn btn-ghost btn-sm">
                  <Icon name="clock" />
                  History
                </button>
                <button className="btn btn-primary btn-sm">
                  <Icon name="check" />
                  Save
                </button>
              </div>
            </div>
            <div
              className="card-body"
              style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}
            >
              <div className="field">
                <label htmlFor="prompt-system" className="label">
                  System
                </label>
                <textarea
                  id="prompt-system"
                  className="textarea editor"
                  rows={5}
                  defaultValue={systemPrompt}
                />
              </div>
              <div className="field">
                <label htmlFor="prompt-user-instruction" className="label">
                  User instruction
                </label>
                <textarea
                  id="prompt-user-instruction"
                  className="textarea editor"
                  rows={3}
                  defaultValue={userInstruction}
                />
              </div>
              <div>
                <div className="label" style={{ marginBottom: '8px' }}>
                  Detected variables
                </div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  <span className="var">{'{context}'}</span>
                  <span className="var">{'{n}'}</span>
                  <span className="var">{'{max_words}'}</span>
                  <span className="var">{'{lang}'}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="grid-2">
            <div className="card">
              <div className="card-head">
                <div>
                  <div className="card-title">Default parameters</div>
                </div>
              </div>
              <div
                className="card-body"
                style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}
              >
                <div className="field">
                  <label htmlFor="prompt-model" className="label">
                    Model
                  </label>
                  <select id="prompt-model" className="select" defaultValue="gpt-4o-mini">
                    <option>gpt-4o-mini</option>
                    <option>gpt-4o</option>
                    <option>claude-3.5-sonnet</option>
                  </select>
                </div>
                <div style={{ display: 'flex', gap: '12px' }}>
                  <div className="field" style={{ flex: 1 }}>
                    <label htmlFor="prompt-temperature" className="label">
                      Temperature
                    </label>
                    <input id="prompt-temperature" className="input" defaultValue="0.3" />
                  </div>
                  <div className="field" style={{ flex: 1 }}>
                    <label htmlFor="prompt-max-words" className="label">
                      max_words
                    </label>
                    <input id="prompt-max-words" className="input" defaultValue="60" />
                  </div>
                </div>
              </div>
            </div>
            <div className="card">
              <div className="card-head">
                <div>
                  <div className="card-title">Quick test</div>
                  <div className="card-desc">Run on an excerpt</div>
                </div>
                <button className="btn btn-outline btn-sm">
                  <Icon name="play" />
                  Test
                </button>
              </div>
              <div className="card-body" style={{ paddingTop: 0 }}>
                <div
                  style={{
                    background: 'var(--muted)',
                    border: '1px solid var(--border)',
                    borderRadius: '9px',
                    padding: '12px 14px',
                    fontSize: '12.5px',
                  }}
                >
                  <div
                    style={{
                      fontFamily: "'Geist Mono', monospace",
                      color: 'var(--muted-foreground)',
                      fontSize: '11.5px',
                      marginBottom: '8px',
                    }}
                  >
                    {'// test output'}
                  </div>
                  <div style={{ fontWeight: 500 }}>Q: How do I launch the application?</div>
                  <div className="muted" style={{ marginTop: '5px', lineHeight: 1.5 }}>
                    A: Run <code>make start</code> after configuring the .env file.
                  </div>
                  <div style={{ marginTop: '10px' }}>
                    <span className="badge badge-success">
                      <span className="dot"></span>score 0.95
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
