'use client'

import { useMemo, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import type { GitHubRepoSummary, RecipeIn } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatCount, timeAgo } from '@/components/hub/format'
import { cn } from '@/lib/utils'
import { docsMode, findSource } from './recipe-state'

type Translate = ReturnType<typeof useTranslations<'github'>>

function selectionLabel(t: Translate, recipe: RecipeIn, repo: string): string | null {
  const source = findSource(recipe, repo)
  if (!source) return null
  const mode = docsMode(source)
  const docs =
    mode === 'default'
      ? t('repos.selection.defaultDocs')
      : mode === 'none'
        ? t('repos.selection.noDocs')
        : t('repos.selection.docs', { count: source.docs?.length ?? 0 })
  return source.readme ? t('repos.selection.withReadme', { docs }) : docs
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
  const t = useTranslations('github')
  const locale = useLocale()
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
            placeholder={t('repos.searchPlaceholder')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <select
          className="select gh-lang"
          aria-label={t('repos.language')}
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
        >
          <option value="">{t('repos.allLanguages')}</option>
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
          {t('repos.selectedOnly')}
        </label>
        {hidden > 0 && (
          <label className="gh-toggle">
            <input
              type="checkbox"
              checked={showAll}
              onChange={(e) => setShowAll(e.target.checked)}
            />
            {t('repos.showHidden', { count: hidden })}
          </label>
        )}
        <span className="hint">
          {t('repos.shownOf', { shown: shown.length, total: repos.length })}
        </span>
      </div>

      {shown.length === 0 ? (
        <p className="muted hub-none">{t('repos.noMatch')}</p>
      ) : (
        <ul className="gh-repo-list">
          {shown.map((repo) => {
            const label = recipe ? selectionLabel(t, recipe, repo.name) : null
            return (
              <li key={repo.name} className={cn('gh-repo', open === repo.name && 'is-open')}>
                {/* The label widens the hit area around the box, not the layout. */}
                <label className="gh-repo-pick">
                  <input
                    type="checkbox"
                    className="gh-repo-check"
                    aria-label={t('repos.useInRecipe', { repo: repo.name })}
                    checked={label !== null}
                    disabled={!recipe || !repo.eligible}
                    onChange={(e) => onToggle(repo.name, e.target.checked)}
                  />
                </label>
                <button type="button" className="gh-repo-main" onClick={() => onOpen(repo.name)}>
                  <span className="gh-repo-name">
                    {repo.name}
                    {repo.fork && <span className="tag">{t('repos.fork')}</span>}
                    {repo.archived && <span className="tag">{t('repos.archived')}</span>}
                  </span>
                  {repo.description && <span className="gh-repo-desc">{repo.description}</span>}
                  <span className="gh-repo-meta">
                    {repo.language && <span>{repo.language}</span>}
                    <span>★ {formatCount(repo.stars, locale)}</span>
                    <span>{timeAgo(repo.pushed_at, now, locale)}</span>
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
