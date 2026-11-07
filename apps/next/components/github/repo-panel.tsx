'use client'

import { useState } from 'react'
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

function DocPreview({ owner, repo, path }: { owner: string; repo: string; path: string }) {
  const doc = useGitHubDoc(owner, repo, path)
  if (doc.isPending) return <p className="muted">Reading {path}…</p>
  if (doc.error) return <p className="hub-error">{doc.error.message}</p>
  return (
    <div className="gh-doc">
      <div className="hint">
        {doc.data.truncated
          ? `The model reads the first ${formatCount(doc.data.max_chars)} characters.`
          : 'The model reads all of it.'}
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
  const [preview, setPreview] = useState<string | null>(null)
  const source = recipe ? findSource(recipe, detail.name) : undefined
  const defaultPick = detail.docs.filter((d) => d.selected_by_default).map((d) => d.path)
  const mode = docsMode(source)

  if (detail.docs.length === 0) {
    return <p className="muted">This repo has no Markdown or text file under docs/.</p>
  }
  return (
    <div className="gh-docs">
      {recipe && source && (
        <fieldset className="tabs gh-docs-mode">
          <legend className="sr-only">Which docs files to use</legend>
          {(['default', 'custom', 'none'] as DocsMode[]).map((m) => (
            <button
              key={m}
              type="button"
              className={cn('tab', mode === m && 'active')}
              aria-pressed={mode === m}
              onClick={() => onChange(setDocsMode(recipe, detail.name, m, defaultPick))}
            >
              {m === 'default' ? 'Default pick' : m === 'custom' ? 'Choose files' : 'None'}
            </button>
          ))}
        </fieldset>
      )}
      <p className="hint">
        The default pick is the first {detail.limits.docs_per_repo} readable files. Files over{' '}
        {formatBytes(detail.limits.doc_bytes)} are skipped; each is cut at{' '}
        {formatCount(detail.limits.doc_chars)} characters.
      </p>
      <ul className="gh-doc-list">
        {detail.docs.map((doc) => {
          const on = docSelected(source, doc.path, defaultPick)
          return (
            <li key={doc.path} className={cn(preview === doc.path && 'is-open')}>
              <input
                type="checkbox"
                aria-label={`Use ${doc.path}`}
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
                {formatBytes(doc.size)}
                {!doc.readable && ' · too large'}
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
              aria-label="Open on GitHub"
            >
              <Icon name="external" />
            </a>
          )}
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
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
            Use this repo
          </label>
          <label className="gh-toggle">
            <input
              type="checkbox"
              checked={source?.readme ?? false}
              disabled={!source}
              onChange={(e) => onChange(setReadme(recipe, repo, e.target.checked))}
            />
            README and metadata
          </label>
          {!eligible && <span className="hint">Forks and archived repos are left out.</span>}
        </div>
      )}

      <div className="tabs gh-panel-tabs" role="tablist" aria-label="Repo sections">
        {(
          [
            ['overview', 'What the model sees'],
            ['readme', 'README'],
            ['docs', `Docs${query.data ? ` (${query.data.docs.length})` : ''}`],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={cn('tab', tab === key && 'active')}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="gh-panel-body">
        {query.isPending && <p className="muted">Reading {repo} on GitHub…</p>}
        {query.error && <p className="hub-error">{query.error.message}</p>}
        {query.data && tab === 'overview' && (
          <div className="gh-overview">
            <div className="hub-chips">
              {query.data.language && <span className="tag">{query.data.language}</span>}
              {(query.data.technologies ?? []).map((t) => (
                <span key={t} className="tag">
                  {t}
                </span>
              ))}
              {(query.data.topics ?? []).map((t) => (
                <span key={`topic-${t}`} className="tag muted">
                  #{t}
                </span>
              ))}
            </div>
            <p className="hint">
              The overview call gets exactly this text ({formatCount(query.data.model_input.length)}{' '}
              characters); its hash decides whether the next run regenerates it.
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
                    Cut at {formatCount(query.data.limits.readme_chars)} characters: the model reads
                    no more.
                  </p>
                )}
              </>
            ) : (
              <p className="muted">No README.</p>
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
