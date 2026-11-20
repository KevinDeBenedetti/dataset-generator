'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useTranslations } from 'next-intl'
import { Icon } from '@/components/app/icon'
import { usePrompts } from '@/hooks'
import './prompts.css'

// Template variables like {context} / {target_language} inside a prompt body.
function detectVariables(content: string): string[] {
  const matches = content.match(/\{[a-z_]+\}/gi) ?? []
  return [...new Set(matches)]
}

export default function PromptsPage() {
  const t = useTranslations('prompts')
  const tc = useTranslations('common')
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
          <h1 className="page-title">{t('title')}</h1>
          <p className="page-sub">{t('subtitle')}</p>
        </div>
      </div>

      {/* isPending (not isLoading) so the skeleton also covers a paused query
          (e.g. the browser reports offline) instead of rendering nothing. */}
      {promptsQuery.isPending && (
        <div className="card">
          <div className="card-body" style={{ paddingTop: 20 }}>
            <p className="muted">{t('loading')}</p>
          </div>
        </div>
      )}
      {promptsQuery.isError && (
        <div className="card">
          <div className="card-body" style={{ paddingTop: 20 }}>
            <p className="hint" style={{ color: 'var(--destructive)' }}>
              {promptsQuery.error instanceof Error ? promptsQuery.error.message : t('loadFailed')}
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
                      {t('active')}
                    </span>
                  ) : (
                    <span className="tag" style={{ fontSize: '11px' }}>
                      {t('legacy')}
                    </span>
                  )}
                </div>
                <div className="pm">
                  {p.role} · {p.model || t('defaultModel')}
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
                    {copied ? tc('copied') : tc('copy')}
                  </button>
                </div>
              </div>
              <div
                className="card-body"
                style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}
              >
                <div className="field">
                  <label htmlFor="prompt-content" className="label">
                    {t('promptLabel', { role: selected.role })}
                  </label>
                  <textarea
                    id="prompt-content"
                    className="textarea editor"
                    rows={14}
                    readOnly
                    value={selected.content}
                  />
                  <div className="hint">{t('readOnlyHint')}</div>
                </div>
                {variables.length > 0 && (
                  <div>
                    <div className="label" style={{ marginBottom: '8px' }}>
                      {t('variables')}
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
                  <div className="card-title">{t('parameters.title')}</div>
                  <div className="card-desc">{t('parameters.description')}</div>
                </div>
                {selected.key === 'qa_agent' && (
                  <Link className="btn btn-outline btn-sm" href="/agent-test">
                    <Icon name="play" />
                    {t('parameters.test')}
                  </Link>
                )}
              </div>
              <div
                className="card-body"
                style={{ paddingTop: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}
              >
                <div
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                >
                  <div className="label">{t('parameters.model')}</div>
                  <span className="tag">{selected.model || t('parameters.default')}</span>
                </div>
                <hr className="sep" />
                <div
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                >
                  <div className="label">{t('parameters.sentAs')}</div>
                  <span className="tag">
                    {t('parameters.roleMessage', { role: selected.role })}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
