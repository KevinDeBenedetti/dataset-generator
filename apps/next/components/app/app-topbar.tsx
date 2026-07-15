'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Icon } from '@/components/app/icon'
import { useIsDark } from '@/hooks/use-is-dark'
import { useCurrentUser, useLogout } from '@/hooks/use-auth'
import { toggleTheme } from '@/lib/utils'

const LABELS: Record<string, string> = {
  '/dashboard': 'Overview',
  '/datasets': 'Datasets',
  '/generate': 'Generation',
  '/sources': 'Sources',
  '/quality': 'Quality control',
  '/jobs': 'Jobs & batch',
  '/agent-test': 'Verify QA',
  '/prompts': 'LLM Prompts',
  '/exports': 'Exports',
  '/api-keys': 'API keys',
  '/settings': 'Settings',
  '/dataset-detail': 'Dataset detail',
}

function labelFor(pathname: string) {
  if (LABELS[pathname]) return LABELS[pathname]
  const seg = pathname.split('/').find(Boolean) ?? ''
  if (!seg) return 'Overview'
  return seg.charAt(0).toUpperCase() + seg.slice(1)
}

export function AppTopbar() {
  const pathname = usePathname() ?? '/dashboard'
  const dark = useIsDark()
  const { data: user } = useCurrentUser()
  const logoutMutation = useLogout()

  return (
    <header className="topbar">
      <div className="crumbs">
        <Icon name="layers" className="ic-sm" />
        <span className="crumb-muted">DatasetGen</span>
        <Icon name="chevronRight" />
        <span>{labelFor(pathname)}</span>
      </div>
      <label className="topbar-search">
        <Icon name="search" />
        <input placeholder="Search datasets, sources, jobs…" />
        <span className="kbd">⌘K</span>
      </label>
      <div className="topbar-spacer" />
      <a
        className="icon-btn"
        title="Documentation"
        href="https://github.com/KevinDeBenedetti/dataset-generator"
        target="_blank"
        rel="noreferrer"
      >
        <Icon name="book" />
      </a>
      <button
        className="icon-btn"
        title="Theme"
        aria-label="Toggle theme"
        onClick={toggleTheme}
        type="button"
      >
        <Icon name={dark ? 'moon' : 'sun'} />
      </button>
      <button className="icon-btn" title="Notifications" type="button">
        <span className="ping" />
        <Icon name="bell" />
      </button>
      <div className="vsep" style={{ height: 22 }} />
      <Link className="btn btn-primary btn-sm" href="/generate">
        <Icon name="plus" />
        New dataset
      </Link>
      {user && (
        <>
          <div className="vsep" style={{ height: 22 }} />
          <span className="crumb-muted" title={`${user.email} (${user.role})`}>
            <Icon name="user" className="ic-sm" />
            {user.email}
          </span>
          <button
            className="icon-btn"
            title="Sign out"
            aria-label="Sign out"
            type="button"
            disabled={logoutMutation.isPending}
            onClick={() => logoutMutation.mutate()}
          >
            <Icon name="logout" />
          </button>
        </>
      )}
    </header>
  )
}
