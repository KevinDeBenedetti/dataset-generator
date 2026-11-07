'use client'

import Link from 'next/link'
import { useState } from 'react'
import { errorStatus } from '@/api/sdk'
import type { GitHubProfileOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatCount } from '@/components/hub/format'
import { initialsFor } from '@/lib/utils'

function resetsIn(resetAt: string | null | undefined, now: number): string {
  if (!resetAt) return ''
  const minutes = Math.max(0, Math.round((new Date(resetAt).getTime() - now) / 60_000))
  return minutes < 1 ? 'resets now' : `resets in ${minutes} min`
}

/** Your account and the API quota left — the page's header. */
export function AccountCard({ profile }: { profile: GitHubProfileOut }) {
  const [now] = useState(() => Date.now())
  const quota = profile.rate_limit
  const low = quota.limit > 0 && quota.remaining / quota.limit < 0.1
  return (
    <div className="card gh-account">
      <span className="avatar gh-avatar" aria-hidden="true">
        {initialsFor(profile.login)}
      </span>
      <div className="gh-account-text">
        <div className="gh-account-name">
          {profile.name || profile.login}{' '}
          <a href={profile.html_url} target="_blank" rel="noopener noreferrer" className="mono">
            @{profile.login}
          </a>
        </div>
        {profile.bio && <p className="hint">{profile.bio}</p>}
        <div className="gh-account-meta">
          <span>{formatCount(profile.public_repos)} public repos</span>
          <span>{formatCount(profile.followers)} followers</span>
          {profile.location && <span>{profile.location}</span>}
        </div>
      </div>
      <div className={`gh-quota${low ? ' is-low' : ''}`}>
        <div className="gh-quota-val">
          {formatCount(quota.remaining)}
          <span className="muted"> / {formatCount(quota.limit)}</span>
        </div>
        <div className="hint">GitHub requests left · {resetsIn(quota.reset_at, now)}</div>
        {!quota.authenticated && (
          <div className="hint">
            <Link href="/settings">Add a GitHub token</Link> to raise it to 5,000 an hour.
          </div>
        )}
      </div>
    </div>
  )
}

/** What the page says when it can't read your account. */
export function GitHubProblem({ error }: { error: Error }) {
  const status = errorStatus(error)
  return (
    <div className="card hub-empty">
      <span className="cell-ic ic-lg">
        <Icon name={status === 400 ? 'github' : 'alert'} className="ic-lg" />
      </span>
      <div>
        <div className="card-title">
          {status === 400
            ? 'Connect your GitHub account'
            : status === 429
              ? 'GitHub rate limit reached'
              : "Couldn't read GitHub"}
        </div>
        <p className="card-desc">
          {status === 400
            ? 'Save your GitHub username in Settings: this page reads its public repos, READMEs and docs.'
            : error.message}
        </p>
      </div>
      {(status === 400 || status === 429) && (
        <Link className="btn btn-primary" href="/settings">
          <Icon name="settings" />
          Open Settings
        </Link>
      )}
    </div>
  )
}
