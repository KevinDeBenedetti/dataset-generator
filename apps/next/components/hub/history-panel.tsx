'use client'

import { useState } from 'react'
import type { HubRepoRef } from '@/api/sdk'
import type { HubCommit, HubDatasetDetail } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { useHubCommits, useHubCompare } from '@/hooks'
import { cn } from '@/lib/utils'
import { compactJson, formatCount, formatDateTime, shortSha, timeAgo } from './format'
import { resolveView } from './data-viewer'
import type { HubViewState } from './url-state'

type Update = (patch: Partial<HubViewState>) => void

// The most telling fields of a row, for a one-line preview in a diff.
function preview(row: Record<string, unknown>): string {
  for (const key of ['question', 'prompt', 'instruction', 'content', 'text', 'title']) {
    if (typeof row[key] === 'string' && row[key]) return row[key] as string
  }
  return compactJson(row)
}

function ChangedRows({
  title,
  sign,
  tone,
  count,
  rows,
}: {
  title: string
  sign: string
  tone: 'added' | 'removed' | 'changed'
  count: number
  rows: { key: string; text: string; before?: string }[]
}) {
  if (count === 0) return null
  return (
    <details className={cn('card hub-diff', `hub-diff-${tone}`)} open={tone !== 'removed'}>
      <summary>
        <span className="hub-diff-sign" aria-hidden="true">
          {sign}
        </span>
        {title}
        <span className="muted">
          {formatCount(count)}
          {count > rows.length ? `, first ${rows.length} shown` : ''}
        </span>
      </summary>
      <ul>
        {rows.map((row) => (
          <li key={row.key}>
            {row.before != null && <span className="hub-diff-before">{row.before}</span>}
            <span>{row.text}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}

function Compare({
  repo,
  detail,
  state,
  update,
}: {
  repo: HubRepoRef
  detail: HubDatasetDetail
  state: HubViewState
  update: Update
}) {
  const current = resolveView(detail.views, state.config, state.split)
  const compare = useHubCompare(
    repo,
    state.base
      ? {
          base: state.base,
          head: state.head ?? detail.sha,
          config: current?.config ?? null,
          split: current?.split ?? null,
        }
      : null,
  )
  if (!state.base) return null
  const data = compare.data
  return (
    <section className="card hub-compare" aria-live="polite">
      <div className="card-head">
        <div>
          <div className="card-title">
            Changes from <span className="mono">{shortSha(state.base)}</span> to{' '}
            <span className="mono">{shortSha(state.head ?? detail.sha)}</span>
          </div>
          <div className="card-desc">
            {current ? `${current.split} split` : 'Default split'}
            {data && (data.key === 'id' ? ', rows matched by id' : ', rows matched by content')}
          </div>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={() => update({ base: null, head: null })}
          aria-label="Close the comparison"
        >
          <Icon name="x" />
        </button>
      </div>
      <div className="card-body">
        {compare.isPending && (
          <p className="muted">
            <Icon name="loader" className="animate-spin" /> Reading both versions…
          </p>
        )}
        {compare.error && <p className="hub-error">{compare.error.message}</p>}
        {data && (
          <>
            <div className="hub-diff-counts">
              <span>
                <b>+{formatCount(data.added)}</b> added
              </span>
              <span>
                <b>−{formatCount(data.removed)}</b> removed
              </span>
              <span>
                <b>~{formatCount(data.changed)}</b> changed
              </span>
              <span className="muted">
                {formatCount(data.unchanged)} unchanged · {formatCount(data.base_rows)} →{' '}
                {formatCount(data.head_rows)} rows
              </span>
            </div>
            {data.added + data.removed + data.changed === 0 && (
              <p className="muted">The rows of this split are identical in both versions.</p>
            )}
            <ChangedRows
              title="Added"
              sign="+"
              tone="added"
              count={data.added}
              rows={data.added_examples.map((row, i) => ({
                key: `a${i}`,
                text: preview(row),
              }))}
            />
            <ChangedRows
              title="Changed"
              sign="~"
              tone="changed"
              count={data.changed}
              rows={data.changed_examples.map((pair, i) => ({
                key: `c${i}`,
                before: compactJson(pair.before),
                text: compactJson(pair.after),
              }))}
            />
            <ChangedRows
              title="Removed"
              sign="−"
              tone="removed"
              count={data.removed}
              rows={data.removed_examples.map((row, i) => ({
                key: `r${i}`,
                text: preview(row),
              }))}
            />
          </>
        )}
      </div>
    </section>
  )
}

export function HistoryPanel({
  repo,
  detail,
  state,
  update,
}: {
  repo: HubRepoRef
  detail: HubDatasetDetail
  state: HubViewState
  update: Update
}) {
  const commits = useHubCommits(repo)
  const [now] = useState(() => Date.now())
  const list: HubCommit[] = commits.data?.commits ?? []
  const latest = list[0]?.id

  return (
    <div className="hub-history">
      <Compare repo={repo} detail={detail} state={state} update={update} />
      <div className="card">
        <div className="card-head">
          <div>
            <div className="card-title">Versions</div>
            <div className="card-desc">
              Every commit to the repo is a version of the dataset, newest first.
              {commits.data && commits.data.total > list.length
                ? ` The ${list.length} most recent of ${formatCount(commits.data.total)}.`
                : ''}
            </div>
          </div>
        </div>
        <div className="card-body">
          {commits.isPending && <p className="muted">Loading the history…</p>}
          {commits.error && <p className="hub-error">{commits.error.message}</p>}
          <ol className="hub-timeline">
            {list.map((commit, index) => {
              const previous = list[index + 1]
              const viewing = commit.id === detail.sha
              return (
                <li key={commit.id} className={cn('hub-commit', viewing && 'is-current')}>
                  <span className="hub-commit-dot" aria-hidden="true">
                    <Icon name={index === 0 ? 'sparkles' : 'gitBranch'} className="ic-sm" />
                  </span>
                  <div className="hub-commit-body">
                    <div className="hub-commit-title">
                      <b>{commit.title || 'Untitled commit'}</b>
                      {commit.id === latest && (
                        <span className="badge badge-success">
                          <span className="dot" />
                          Latest
                        </span>
                      )}
                      {viewing && <span className="badge badge-info">Viewing</span>}
                    </div>
                    <div className="hint">
                      <a
                        className="mono"
                        href={`${detail.url}/commit/${commit.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {shortSha(commit.id)}
                      </a>
                      {commit.authors.length > 0 && ` · ${commit.authors.join(', ')}`}
                      {' · '}
                      <span title={formatDateTime(commit.created_at)}>
                        {timeAgo(commit.created_at, now)}
                      </span>
                    </div>
                  </div>
                  <div className="hub-commit-actions">
                    {!viewing && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() =>
                          update({
                            rev: commit.id === latest ? null : commit.id,
                            tab: 'data',
                            base: null,
                            head: null,
                            row: null,
                          })
                        }
                      >
                        <Icon name="eye" />
                        Browse
                      </button>
                    )}
                    {previous && (
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={() => update({ base: previous.id, head: commit.id })}
                      >
                        <Icon name="merge" />
                        Changes
                      </button>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      </div>
    </div>
  )
}
