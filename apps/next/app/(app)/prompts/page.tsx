'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Icon } from '@/components/app/icon'
import { usePrompts } from '@/hooks'
import './prompts.css'

// Template variables like {context} / {target_language} inside a prompt body.
function detectVariables(content: string): string[] {
  const matches = content.match(/\{[a-z_]+\}/gi) ?? []
  return [...new Set(matches)]
}

export default function PromptsPage() {
  const promptsQuery = usePrompts()
  const prompts = promptsQuery.data?.prompts ?? []
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const selected = prompts.find((p) => p.key === selectedKey) ?? prompts[0] ?? null
  const variables = selected ? detectVariables(selected.content) : []

  const copyPrompt = async () => {
    if (!selected) return
    try {
      await navigator.clipboard.writeText(selected.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard unavailable (permissions/insecure context) — nothing to do.
    }
  }

  return (
    <div className="prompts-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">LLM Prompts</h1>
          <p className="page-sub">
            The prompts the app really sends to the models — cleaning, transcription and QA
            generation. They live in the server code and change with a deploy.
          </p>
        </div>
      </div>

      {/* isPending (not isLoading) so the skeleton also covers a paused query
          (e.g. the browser reports offline) instead of rendering nothing. */}
      {promptsQuery.isPending && (
        <div className="card">
          <div className="card-body" style={{ paddingTop: 20 }}>
            <p className="muted">Loading prompts…</p>
          </div>
        </div>
      )}
      {promptsQuery.isError && (
        <div className="card">
          <div className="card-body" style={{ paddingTop: 20 }}>
            <p className="hint" style={{ color: 'var(--destructive)' }}>
              {promptsQuery.error instanceof Error
                ? promptsQuery.error.message
                : 'Failed to load prompts'}
            </p>
          </div>
        </div>
      )}

      {selected && (
        <div className="pe">
          <div className="plist">
            {prompts.map((p) => (
              <button
                type="button"
                key={p.key}
                className={p.key === selected.key ? 'pitem sel' : 'pitem'}
                style={{ textAlign: 'left', width: '100%' }}
                onClick={() => setSelectedKey(p.key)}
              >
                <div className="pn">
                  {p.label}{' '}
                  {p.active ? (
                    <span className="badge badge-success" style={{ height: '18px' }}>
                      <span className="dot"></span>
                      active
                    </span>
                  ) : (
                    <span className="tag" style={{ fontSize: '11px' }}>
                      legacy
                    </span>
                  )}
                </div>
                <div className="pm">
                  {p.role} · {p.model || 'default model'}
                </div>
              </button>
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
                    {selected.label} <span className="tag">{selected.role}</span>
                  </div>
                  <div className="card-desc">{selected.used_by}</div>
                </div>
                <div className="page-actions">
                  <button className="btn btn-outline btn-sm" onClick={copyPrompt} type="button">
                    <Icon name={copied ? 'check' : 'copy'} />
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>
              </div>
              <div
                className="card-body"
                style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}
              >
                <div className="field">
                  <label htmlFor="prompt-content" className="label">
                    Prompt ({selected.role})
                  </label>
                  <textarea
                    id="prompt-content"
                    className="textarea editor"
                    rows={14}
                    readOnly
                    value={selected.content}
                  />
                  <div className="hint">
                    Read-only: prompts are versioned with the code (apps/server/services). Edit
                    them there and redeploy.
                  </div>
                </div>
                {variables.length > 0 && (
                  <div>
                    <div className="label" style={{ marginBottom: '8px' }}>
                      Detected variables
                    </div>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      {variables.map((v) => (
                        <span className="var" key={v}>
                          {v}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card-head">
                <div>
                  <div className="card-title">Default parameters</div>
                  <div className="card-desc">From the server configuration (.env)</div>
                </div>
                {selected.key === 'qa_agent' && (
                  <Link className="btn btn-outline btn-sm" href="/agent-test">
                    <Icon name="play" />
                    Test on /agent-test
                  </Link>
                )}
              </div>
              <div
                className="card-body"
                style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div className="label">Model</div>
                  <span className="tag">{selected.model || 'default'}</span>
                </div>
                <hr className="sep" />
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div className="label">Sent as</div>
                  <span className="tag">{selected.role} message</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
