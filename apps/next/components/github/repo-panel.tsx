'use client'

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import type { GitHubRepoDetail, RecipeIn } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatBytes, formatCount } from '@/components/hub/format'
import { Markdown } from '@/components/hub/markdown'
import { useGitHubDoc, useGitHubRepo } from '@/hooks'
import { cn } from '@/lib/utils'
import {
  type DocsMode,
  docSelected,
  docsMode,
  findSource,
  setDocsMode,
  setReadme,
  toggleDoc,
  toggleRepo,
} from './recipe-state'

type Tab = 'overview' | 'readme' | 'docs'

// The labels are the `github.docs.modes.<mode>` and `github.panel.tabs.<tab>` messages.
const DOCS_MODES: DocsMode[] = ['default', 'custom', 'none']
const TABS: Tab[] = ['overview', 'readme', 'docs']

function DocPreview({ owner, repo, path }: { owner: string; repo: string; path: string }) {
  const t = useTranslations('github')
  const locale = useLocale()
  const doc = useGitHubDoc(owner, repo, path)
  if (doc.isPending) return <p className="muted">{t('docs.reading', { path })}</p>
  if (doc.error) return <p className="hub-error">{doc.error.message}</p>
  return (
    <div className="gh-doc">
      <div className="hint">
        {doc.data.truncated
          ? t('docs.truncated', { count: formatCount(doc.data.max_chars, locale) })
          : t('docs.whole')}
      </div>
      <div className="hub-markdown gh-doc-body">
        <Markdown>{doc.data.content}</Markdown>
      </div>
    </div>
  )
}

function Docs({
  detail,
  owner,
  recipe,
  onChange,
}: {
  detail: GitHubRepoDetail
  owner: string
  recipe: RecipeIn | null
  onChange: (recipe: RecipeIn) => void
}) {
  const t = useTranslations('github')
  const locale = useLocale()
  const tc = useTranslations('common')
  const [preview, setPreview] = useState<string | null>(null)
  const source = recipe ? findSource(recipe, detail.name) : undefined
  const defaultPick = detail.docs.filter((d) => d.selected_by_default).map((d) => d.path)
  const mode = docsMode(source)

  if (detail.docs.length === 0) {
    return <p className="muted">{t('docs.none')}</p>
  }
  return (
    <div className="gh-docs">
      {recipe && source && (
        <fieldset className="tabs gh-docs-mode">
          <legend className="sr-only">{t('docs.modeLegend')}</legend>
          {DOCS_MODES.map((m) => (
            <button
              key={m}
              type="button"
              className={cn('tab', mode === m && 'active')}
              aria-pressed={mode === m}
              onClick={() => onChange(setDocsMode(recipe, detail.name, m, defaultPick))}
            >
              {m === 'none' ? tc('none') : t(`docs.modes.${m}`)}
            </button>
          ))}
        </fieldset>
      )}
      <p className="hint">
        {t('docs.limits', {
          files: detail.limits.docs_per_repo,
          size: formatBytes(detail.limits.doc_bytes, locale),
          chars: formatCount(detail.limits.doc_chars, locale),
        })}
      </p>
      <ul className="gh-doc-list">
        {detail.docs.map((doc) => {
          const on = docSelected(source, doc.path, defaultPick)
          return (
            <li key={doc.path} className={cn(preview === doc.path && 'is-open')}>
              <input
                type="checkbox"
                aria-label={t('docs.use', { path: doc.path })}
                checked={on}
                disabled={!recipe || !source || !doc.readable}
                onChange={() =>
                  recipe && onChange(toggleDoc(recipe, detail.name, doc.path, defaultPick))
                }
              />
              <button
                type="button"
                className="gh-doc-path mono"
                onClick={() => setPreview(preview === doc.path ? null : doc.path)}
              >
                {doc.path}
              </button>
              <span className="hint">
                {formatBytes(doc.size, locale)}
                {!doc.readable && ` · ${t('docs.tooLarge')}`}
              </span>
            </li>
          )
        })}
      </ul>
      {preview && <DocPreview owner={owner} repo={detail.name} path={preview} />}
    </div>
  )
}

/** One repo as the model sees it, and what the recipe takes from it. */
export function RepoPanel({
  owner,
  repo,
  eligible,
  recipe,
  onChange,
  onClose,
}: {
  owner: string
  repo: string
  eligible: boolean
  recipe: RecipeIn | null
  onChange: (recipe: RecipeIn) => void
  onClose: () => void
}) {
  const t = useTranslations('github')
  const locale = useLocale()
  const tc = useTranslations('common')
  const [tab, setTab] = useState<Tab>('overview')
  const query = useGitHubRepo(owner, repo)
  const source = recipe ? findSource(recipe, repo) : undefined

  return (
    <section className="card gh-panel" aria-label={repo}>
      <header className="gh-panel-head">
        <div>
          <h2 className="card-title">{repo}</h2>
          {query.data?.description && <p className="card-desc">{query.data.description}</p>}
        </div>
        <div className="gh-panel-actions">
          {query.data && (
            <a
              className="icon-btn"
              href={query.data.html_url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t('panel.openOnGitHub')}
            >
              <Icon name="external" />
            </a>
          )}
          <button type="button" className="icon-btn" onClick={onClose} aria-label={tc('close')}>
            <Icon name="x" />
          </button>
        </div>
      </header>

      {recipe && (
        <div className="gh-panel-pick">
          <label className="gh-toggle">
            <input
              type="checkbox"
              checked={Boolean(source)}
              disabled={!eligible}
              onChange={(e) => onChange(toggleRepo(recipe, repo, e.target.checked))}
            />
            {t('panel.useRepo')}
          </label>
          <label className="gh-toggle">
            <input
              type="checkbox"
              checked={source?.readme ?? false}
              disabled={!source}
              onChange={(e) => onChange(setReadme(recipe, repo, e.target.checked))}
            />
            {t('panel.readmeAndMetadata')}
          </label>
          {!eligible && <span className="hint">{t('panel.notEligible')}</span>}
        </div>
      )}

      <div className="tabs gh-panel-tabs" role="tablist" aria-label={t('panel.sections')}>
        {TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={cn('tab', tab === key && 'active')}
            onClick={() => setTab(key)}
          >
            {key === 'docs' && query.data
              ? t('panel.tabs.docsCount', { count: query.data.docs.length })
              : t(`panel.tabs.${key}`)}
          </button>
        ))}
      </div>

      <div className="gh-panel-body">
        {query.isPending && <p className="muted">{t('panel.reading', { repo })}</p>}
        {query.error && <p className="hub-error">{query.error.message}</p>}
        {query.data && tab === 'overview' && (
          <div className="gh-overview">
            <div className="hub-chips">
              {query.data.language && <span className="tag">{query.data.language}</span>}
              {(query.data.technologies ?? []).map((tech) => (
                <span key={tech} className="tag">
                  {tech}
                </span>
              ))}
              {(query.data.topics ?? []).map((topic) => (
                <span key={`topic-${topic}`} className="tag muted">
                  #{topic}
                </span>
              ))}
            </div>
            <p className="hint">
              {t('panel.modelInput', { count: formatCount(query.data.model_input.length, locale) })}
            </p>
            <pre className="hub-pre gh-model-input">{query.data.model_input}</pre>
          </div>
        )}
        {query.data && tab === 'readme' && (
          <div className="hub-markdown gh-readme">
            {query.data.readme ? (
              <>
                <Markdown>{query.data.readme}</Markdown>
                {query.data.readme_truncated && (
                  <p className="hint">
                    {t('panel.readmeCut', {
                      count: formatCount(query.data.limits.readme_chars, locale),
                    })}
                  </p>
                )}
              </>
            ) : (
              <p className="muted">{t('panel.noReadme')}</p>
            )}
          </div>
        )}
        {query.data && tab === 'docs' && (
          <Docs detail={query.data} owner={owner} recipe={recipe} onChange={onChange} />
        )}
      </div>
    </section>
  )
}
