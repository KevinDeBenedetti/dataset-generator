'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { LanguageSwitch } from '@/components/app/language-switch'
import { Icon } from '@/components/app/icon'
import { useIsDark } from '@/hooks/use-is-dark'
import { useCurrentUser, useLogout } from '@/hooks/use-auth'
import { toggleTheme } from '@/lib/utils'

// The page name in the breadcrumb, by the first segment of its path.
const LABELS = {
  dashboard: 'overview',
  datasets: 'datasets',
  collections: 'collections',
  drafts: 'drafts',
  github: 'github',
  resume: 'resume',
  generate: 'generate',
  quality: 'qualityControl',
  'agent-test': 'verifyQa',
  prompts: 'prompts',
  models: 'models',
  settings: 'settings',
  admin: 'backoffice',
} as const

function labelKeyFor(pathname: string) {
  const seg = pathname.split('/').find(Boolean) ?? ''
  return LABELS[seg as keyof typeof LABELS] ?? 'overview'
}

// Documentation, language, theme and notifications: in the top bar, and in the
// navigation drawer on phones, where the top bar has no room for them.
export function ShellTools() {
  const dark = useIsDark()
  const t = useTranslations()
  return (
    <>
      <a
        className="icon-btn"
        title={t('shell.documentation')}
        aria-label={t('shell.documentation')}
        href="https://github.com/KevinDeBenedetti/dataset-generator"
        target="_blank"
        rel="noreferrer"
      >
        <Icon name="book" />
      </a>
      <LanguageSwitch className="icon-btn" />
      <button
        className="icon-btn"
        title={t('theme.label')}
        aria-label={t('theme.toggle')}
        onClick={toggleTheme}
        type="button"
      >
        <Icon name={dark ? 'moon' : 'sun'} />
      </button>
      <button
        className="icon-btn"
        title={t('shell.notifications')}
        aria-label={t('shell.notifications')}
        type="button"
      >
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
  const t = useTranslations()

  return (
    <header className="topbar">
      {/* Below the drawer breakpoint the sidebar opens from here. */}
      <button
        ref={menuButtonRef}
        type="button"
        className="icon-btn topbar-menu"
        aria-label={t('shell.openNavigation')}
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
        <span className="crumb-page">{t(`nav.${labelKeyFor(pathname)}`)}</span>
      </div>
      <label className="topbar-search">
        <Icon name="search" />
        <input placeholder={t('shell.searchPlaceholder')} />
        <span className="kbd">⌘K</span>
      </label>
      <div className="topbar-spacer" />
      <div className="topbar-tools">
        <ShellTools />
        <div className="vsep" style={{ height: 22 }} />
      </div>
      <Link className="btn btn-primary btn-sm" href="/generate">
        <Icon name="plus" />
        {t('shell.newDataset')}
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
            title={t('shell.signOut')}
            aria-label={t('shell.signOut')}
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
