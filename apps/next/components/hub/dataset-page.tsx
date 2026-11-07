'use client'

import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'
import { errorStatus, type HubRepoRef } from '@/api/sdk'
import type { HubDatasetDetail } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { useHubCommits, useHubDataset } from '@/hooks'
import { cn } from '@/lib/utils'
import { CardPanel } from './card-panel'
import { DataViewer } from './data-viewer'
import { ConnectHuggingFace } from './datasets-list'
import { FilesPanel } from './files-panel'
import { formatBytes, formatCount, formatDateTime, shortSha, timeAgo } from './format'
import { HistoryPanel } from './history-panel'
import { StatsPanel } from './stats-panel'
import { type HubTab, type HubViewState, useHubUrlState } from './url-state'

const TABS: { key: HubTab; label: string; icon: string }[] = [
  { key: 'data', label: 'Data', icon: 'table' },
  { key: 'card', label: 'Card', icon: 'book' },
  { key: 'stats', label: 'Statistics', icon: 'activity' },
  { key: 'files', label: 'Files', icon: 'fileText' },
  { key: 'history', label: 'History', icon: 'gitBranch' },
]

function RevisionPicker({
  repo,
  detail,
  state,
  update,
}: {
  repo: HubRepoRef
  detail: HubDatasetDetail
  state: HubViewState
  update: (patch: Partial<HubViewState>) => void
}) {
  const commits = useHubCommits(repo)
  const [now] = useState(() => Date.now())
  const branches = (detail.refs.branches ?? []).filter((b) => b.name !== 'main')
  const tags = detail.refs.tags ?? []
  const recent = (commits.data?.commits ?? []).slice(0, 20)
  const known = new Set([
    '',
    ...branches.map((b) => b.name),
    ...tags.map((t) => t.name),
    ...recent.map((c) => c.id),
  ])
  const value = state.rev ?? ''

  return (
    <select
      className="select hub-rev"
      aria-label="Version"
      value={value}
      onChange={(e) => update({ rev: e.target.value || null, row: null, base: null, head: null })}
    >
      <option value="">Latest version</option>
      {!known.has(value) && <option value={value}>{shortSha(value)}</option>}
      {branches.length > 0 && (
        <optgroup label="Branches">
          {branches.map((b) => (
            <option key={b.name} value={b.name}>
              {b.name}
            </option>
          ))}
        </optgroup>
      )}
      {tags.length > 0 && (
        <optgroup label="Tags">
          {tags.map((t) => (
            <option key={t.name} value={t.name}>
              {t.name}
            </option>
          ))}
        </optgroup>
      )}
      {recent.length > 1 && (
        <optgroup label="Commits">
          {recent.map((c) => (
            <option key={c.id} value={c.id}>
              {shortSha(c.id)} · {c.title.slice(0, 48) || 'commit'} · {timeAgo(c.created_at, now)}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  )
}

function Header({
  repo,
  detail,
  state,
  update,
}: {
  repo: HubRepoRef
  detail: HubDatasetDetail
  state: HubViewState
  update: (patch: Partial<HubViewState>) => void
}) {
  const [now] = useState(() => Date.now())
  const title = detail.pretty_name || repo.name
  const tags = (detail.tags ?? []).filter((t) => !t.includes(':'))

  const copySnippet = async () => {
    const snippet = `from datasets import load_dataset\n\nds = load_dataset("${detail.id}")`
    try {
      await navigator.clipboard.writeText(snippet)
      toast.success('Python snippet copied', {
        description: detail.private
          ? 'Private dataset: sign in first with `hf auth login`.'
          : undefined,
      })
    } catch {
      toast.error('The browser refused access to the clipboard')
    }
  }

  return (
    <header className="hub-head">
      <div className="hub-head-main">
        <span className="cell-ic hub-head-ic">
          <Icon name="database" className="ic-lg" />
        </span>
        <div className="hub-head-text">
          <h1 className="page-title hub-title">
            {title}
            {detail.private ? (
              <span className="badge badge-secondary">
                <Icon name="key" className="ic-sm" />
                Private
              </span>
            ) : (
              <span className="badge badge-outline">
                <Icon name="globe" className="ic-sm" />
                Public
              </span>
            )}
            {Boolean(detail.gated) && <span className="badge badge-warning">Gated</span>}
          </h1>
          <div className="hub-meta-line">
            <span className="mono">{detail.id}</span>
            <span title={formatDateTime(detail.last_modified)}>
              Updated {timeAgo(detail.last_modified, now)}
            </span>
            {detail.used_storage != null && <span>{formatBytes(detail.used_storage)}</span>}
            <span>{formatCount(detail.files.length)} files</span>
            <span>{formatCount(detail.downloads ?? 0)} downloads (30 days)</span>
            <span>{formatCount(detail.likes ?? 0)} likes</span>
          </div>
          {detail.description && <p className="hub-desc">{detail.description}</p>}
          <div className="hub-chips">
            {detail.language?.map((lang) => (
              <span key={`lang-${lang}`} className="tag">
                <Icon name="languages" className="ic-sm" />
                {lang}
              </span>
            ))}
            {detail.license && <span className="tag">license: {detail.license}</span>}
            {detail.size_category && <span className="tag mono">{detail.size_category}</span>}
            {tags.map((tag) => (
              <span key={tag} className="tag">
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>
      <div className="page-actions hub-head-actions">
        <RevisionPicker repo={repo} detail={detail} state={state} update={update} />
        <Link
          className="btn btn-outline"
          href={`/generate?target=${encodeURIComponent(detail.id)}`}
        >
          <Icon name="plus" />
          Add data
        </Link>
        <Link
          className="btn btn-outline"
          href={`/collections?repo=${encodeURIComponent(detail.id)}`}
        >
          <Icon name="boxes" />
          Build a collection
        </Link>
        <button type="button" className="btn btn-outline" onClick={copySnippet}>
          <Icon name="terminal" />
          Use in Python
        </button>
        <a className="btn btn-outline" href={detail.url} target="_blank" rel="noopener noreferrer">
          <Icon name="external" />
          Hugging Face
        </a>
      </div>
    </header>
  )
}

export function HubDatasetPage({ repo }: { repo: HubRepoRef }) {
  const [state, update] = useHubUrlState()
  const dataset = useHubDataset(repo, state.rev)
  const status = errorStatus(dataset.error)

  const back = (
    <Link href="/datasets" className="btn btn-ghost btn-sm hub-back">
      <Icon name="chevronLeft" />
      Datasets
    </Link>
  )

  if (dataset.isPending) {
    return (
      <div className="hub-page">
        {back}
        <div className="card hub-loading" aria-busy="true">
          <Icon name="loader" className="animate-spin" />
          Reading {repo.owner}/{repo.name} from Hugging Face…
        </div>
      </div>
    )
  }

  if (dataset.error) {
    return (
      <div className="hub-page">
        {back}
        {status === 503 ? (
          <ConnectHuggingFace message={dataset.error.message} />
        ) : (
          <div className="card hub-empty">
            <span className="cell-ic ic-lg">
              <Icon name="alert" className="ic-lg" />
            </span>
            <div>
              <div className="card-title">
                {status === 404 ? 'Dataset not found' : "Couldn't load this dataset"}
              </div>
              <p className="card-desc">{dataset.error.message}</p>
            </div>
            {state.rev ? (
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => update({ rev: null })}
              >
                Latest version
              </button>
            ) : (
              <button type="button" className="btn btn-outline" onClick={() => dataset.refetch()}>
                <Icon name="refresh" />
                Try again
              </button>
            )}
          </div>
        )}
      </div>
    )
  }

  const detail = dataset.data
  return (
    <div className="hub-page">
      {back}
      <Header repo={repo} detail={detail} state={state} update={update} />

      {state.rev && (
        <div className="hub-notice">
          <Icon name="clock" />
          <span>
            You are viewing an earlier version, commit{' '}
            <span className="mono">{shortSha(detail.sha)}</span>.
          </span>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={() => update({ rev: null, row: null })}
          >
            Back to the latest
          </button>
        </div>
      )}

      <nav className="tabs hub-tabs" aria-label="Dataset sections">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={cn('tab', state.tab === tab.key && 'active')}
            aria-current={state.tab === tab.key ? 'page' : undefined}
            onClick={() => update({ tab: tab.key, row: null })}
          >
            <Icon name={tab.icon} />
            {tab.label}
          </button>
        ))}
      </nav>

      {state.tab === 'data' && (
        <DataViewer repo={repo} detail={detail} state={state} update={update} />
      )}
      {state.tab === 'card' && <CardPanel detail={detail} />}
      {state.tab === 'stats' && (
        <StatsPanel repo={repo} detail={detail} state={state} update={update} />
      )}
      {state.tab === 'files' && <FilesPanel detail={detail} />}
      {state.tab === 'history' && (
        <HistoryPanel repo={repo} detail={detail} state={state} update={update} />
      )}
    </div>
  )
}
