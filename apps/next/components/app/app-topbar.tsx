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
  '/drafts': 'Drafts',
  '/github': 'GitHub',
  '/resume': 'Resume',
  '/generate': 'Generate',
  '/quality': 'Quality control',
  '/agent-test': 'Verify QA',
  '/prompts': 'LLM Prompts',
  '/models': 'Models',
  '/settings': 'Settings',
}

function labelFor(pathname: string) {
  if (LABELS[pathname]) return LABELS[pathname]
  const seg = pathname.split('/').find(Boolean) ?? ''
  if (!seg) return 'Overview'
  return seg.charAt(0).toUpperCase() + seg.slice(1)
}

// Documentation, theme and notifications: in the top bar, and in the
// navigation drawer on phones, where the top bar has no room for them.
export function ShellTools() {
  const dark = useIsDark()
  return (
    <>
      <a
        className="icon-btn"
        title="Documentation"
        aria-label="Documentation"
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
      <button className="icon-btn" title="Notifications" aria-label="Notifications" type="button">
        <span className="ping" />
        <Icon name="bell" />
      </button>
    </>
  )
}

export function AppTopbar({
  menuButtonRef,
  navOpen,
  onOpenNav,
}: {
  menuButtonRef: React.Ref<HTMLButtonElement>
  navOpen: boolean
  onOpenNav: () => void
}) {
  const pathname = usePathname() ?? '/dashboard'
  const { data: user } = useCurrentUser()
  const logoutMutation = useLogout()

  return (
    <header className="topbar">
      {/* Below the drawer breakpoint the sidebar opens from here. */}
      <button
        ref={menuButtonRef}
        type="button"
        className="icon-btn topbar-menu"
        aria-label="Open navigation"
        aria-controls="app-sidebar"
        aria-expanded={navOpen}
        onClick={onOpenNav}
      >
        <Icon name="menu" />
      </button>
      <div className="crumbs">
        {/* The drawer's header carries the product name on phones. */}
        <span className="crumb-brand">
          <Icon name="layers" className="ic-sm" />
          <span className="crumb-muted">DatasetGen</span>
          <Icon name="chevronRight" />
        </span>
        <span className="crumb-page">{labelFor(pathname)}</span>
      </div>
      <label className="topbar-search">
        <Icon name="search" />
        <input placeholder="Search datasets, sources, jobs…" />
        <span className="kbd">⌘K</span>
      </label>
      <div className="topbar-spacer" />
      <div className="topbar-tools">
        <ShellTools />
        <div className="vsep" style={{ height: 22 }} />
      </div>
      <Link className="btn btn-primary btn-sm" href="/generate">
        <Icon name="plus" />
        New dataset
      </Link>
      {/* The sidebar footer shows the same account, so this copy only appears
          on screens wide enough to hold both. */}
      {user && (
        <div className="topbar-user">
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
        </div>
      )}
    </header>
  )
}
