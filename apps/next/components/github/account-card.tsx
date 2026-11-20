'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { errorStatus } from '@/api/sdk'
import type { GitHubProfileOut } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatCount } from '@/components/hub/format'
import { richLink } from '@/lib/rich'
import { initialsFor } from '@/lib/utils'

const settingsLink = richLink('/settings')

/** Minutes until the quota resets, or null when GitHub gave no reset time. */
function minutesToReset(resetAt: string | null | undefined, now: number): number | null {
  if (!resetAt) return null
  return Math.max(0, Math.round((new Date(resetAt).getTime() - now) / 60_000))
}

/** Your account and the API quota left — the page's header. */
export function AccountCard({ profile }: { profile: GitHubProfileOut }) {
  const t = useTranslations('github')
  const locale = useLocale()
  const [now] = useState(() => Date.now())
  const quota = profile.rate_limit
  const low = quota.limit > 0 && quota.remaining / quota.limit < 0.1
  const minutes = minutesToReset(quota.reset_at, now)
  const resets =
    minutes === null
      ? ''
      : minutes < 1
        ? t('account.resetsNow')
        : t('account.resetsIn', { minutes })
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
          <span>
            {t('account.publicRepos', {
              count: profile.public_repos,
              formatted: formatCount(profile.public_repos, locale),
            })}
          </span>
          <span>
            {t('account.followers', {
              count: profile.followers,
              formatted: formatCount(profile.followers, locale),
            })}
          </span>
          {profile.location && <span>{profile.location}</span>}
        </div>
      </div>
      <div className={`gh-quota${low ? ' is-low' : ''}`}>
        <div className="gh-quota-val">
          {formatCount(quota.remaining, locale)}
          <span className="muted"> / {formatCount(quota.limit, locale)}</span>
        </div>
        <div className="hint">
          {t('account.requestsLeft')} · {resets}
        </div>
        {!quota.authenticated && (
          <div className="hint">{t.rich('account.addToken', { link: settingsLink })}</div>
        )}
      </div>
    </div>
  )
}

/** What the page says when it can't read your account. */
export function GitHubProblem({ error }: { error: Error }) {
  const t = useTranslations('github')
  const status = errorStatus(error)
  return (
    <div className="card hub-empty">
      <span className="cell-ic ic-lg">
        <Icon name={status === 400 ? 'github' : 'alert'} className="ic-lg" />
      </span>
      <div>
        <div className="card-title">
          {status === 400
            ? t('problem.connectTitle')
            : status === 429
              ? t('problem.rateLimitTitle')
              : t('problem.readFailedTitle')}
        </div>
        <p className="card-desc">
          {status === 400 ? t('problem.connectDescription') : error.message}
        </p>
      </div>
      {(status === 400 || status === 429) && (
        <Link className="btn btn-primary" href="/settings">
          <Icon name="settings" />
          {t('problem.openSettings')}
        </Link>
      )}
    </div>
  )
}
