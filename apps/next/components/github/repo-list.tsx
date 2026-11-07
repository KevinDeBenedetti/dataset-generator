'use client'

import { useMemo, useState } from 'react'
import type { GitHubRepoSummary, RecipeIn } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatCount, timeAgo } from '@/components/hub/format'
import { cn } from '@/lib/utils'
import { docsMode, findSource } from './recipe-state'

function selectionLabel(recipe: RecipeIn, repo: string): string | null {
  const source = findSource(recipe, repo)
  if (!source) return null
  const mode = docsMode(source)
  const docs =
    mode === 'default'
      ? 'default docs'
      : mode === 'none'
        ? 'no docs'
        : `${source.docs?.length} doc${source.docs?.length === 1 ? '' : 's'}`
  return source.readme ? `README · ${docs}` : docs
}

/** Your repos, with what the recipe takes from each. */
export function RepoList({
  repos,
  recipe,
  open,
  onOpen,
  onToggle,
}: {
  repos: GitHubRepoSummary[]
  recipe: RecipeIn | null
  open: string | null
  onOpen: (repo: string) => void
  onToggle: (repo: string, on: boolean) => void
}) {
  const [query, setQuery] = useState('')
  const [language, setLanguage] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [selectedOnly, setSelectedOnly] = useState(false)
  // One "now" per mount keeps relative times stable across renders.
  const [now] = useState(() => Date.now())

  const languages = useMemo(
    () => [...new Set(repos.map((r) => r.language).filter(Boolean) as string[])].toSorted(),
    [repos],
  )
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return repos.filter(
      (r) =>
        (showAll || r.eligible) &&
        (!language || r.language === language) &&
        (!selectedOnly || (recipe && findSource(recipe, r.name))) &&
        (!needle ||
          [r.name, r.description, ...(r.topics ?? [])].join(' ').toLowerCase().includes(needle)),
    )
  }, [repos, query, language, showAll, selectedOnly, recipe])
  const hidden = repos.filter((r) => !r.eligible).length

  return (
    <div className="card gh-repos">
      <div className="hub-toolbar gh-repos-tools">
        <label className="hub-search">
          <Icon name="search" />
          <input
            type="search"
            placeholder="Search repos, descriptions, topics"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          className="select gh-lang"
          aria-label="Language"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
        >
          <option value="">All languages</option>
          {languages.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
      </div>
      <div className="gh-repos-filters">
        <label className="gh-toggle">
          <input
            type="checkbox"
            checked={selectedOnly}
            onChange={(e) => setSelectedOnly(e.target.checked)}
          />
          Selected only
        </label>
        {hidden > 0 && (
          <label className="gh-toggle">
            <input
              type="checkbox"
              checked={showAll}
              onChange={(e) => setShowAll(e.target.checked)}
            />
            Show forks and archived ({hidden})
          </label>
        )}
        <span className="hint">
          {shown.length} of {repos.length}
        </span>
      </div>

      {shown.length === 0 ? (
        <p className="muted hub-none">No repo matches.</p>
      ) : (
        <ul className="gh-repo-list">
          {shown.map((repo) => {
            const label = recipe ? selectionLabel(recipe, repo.name) : null
            return (
              <li key={repo.name} className={cn('gh-repo', open === repo.name && 'is-open')}>
                <input
                  type="checkbox"
                  className="gh-repo-check"
                  aria-label={`Use ${repo.name} in the recipe`}
                  checked={label !== null}
                  disabled={!recipe || !repo.eligible}
                  onChange={(e) => onToggle(repo.name, e.target.checked)}
                />
                <button type="button" className="gh-repo-main" onClick={() => onOpen(repo.name)}>
                  <span className="gh-repo-name">
                    {repo.name}
                    {repo.fork && <span className="tag">fork</span>}
                    {repo.archived && <span className="tag">archived</span>}
                  </span>
                  {repo.description && <span className="gh-repo-desc">{repo.description}</span>}
                  <span className="gh-repo-meta">
                    {repo.language && <span>{repo.language}</span>}
                    <span>★ {formatCount(repo.stars)}</span>
                    <span>{timeAgo(repo.pushed_at, now)}</span>
                    {label && <span className="gh-repo-picked">{label}</span>}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
