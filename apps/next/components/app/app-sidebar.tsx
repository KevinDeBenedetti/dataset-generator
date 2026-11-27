'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { Icon } from '@/components/app/icon'
import { ShellTools } from '@/components/app/app-topbar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useCollections, useDatasets, useDrafts, useHubDatasets } from '@/hooks'
import { useCurrentUser, useLogout } from '@/hooks/use-auth'
import { cn, initialsFor } from '@/lib/utils'
import pkg from '@/package.json'

type NavItem = {
  icon: string
  // A key of the `nav` messages.
  label:
    | 'overview'
    | 'sources'
    | 'recipes'
    | 'datasets'
    | 'collections'
    | 'drafts'
    | 'github'
    | 'resume'
    | 'generate'
    | 'qualityControl'
    | 'verifyQa'
    | 'prompts'
    | 'models'
  href: string
  count?: string
  // Pages whose routes answer admins only (the server's own keys).
  adminOnly?: boolean
}

const NAV: {
  label: 'platform' | 'otherGenerators' | 'quality' | 'configuration'
  items: NavItem[]
}[] = [
  {
    label: 'platform',
    items: [
      { icon: 'dashboard', label: 'overview', href: '/dashboard' },
      { icon: 'upload', label: 'sources', href: '/sources' },
      { icon: 'filter', label: 'recipes', href: '/recipes' },
      { icon: 'database', label: 'datasets', href: '/datasets' },
      { icon: 'boxes', label: 'collections', href: '/collections' },
    ],
  },
  {
    // Today's generators, until they run as connectors and recipes (#318).
    label: 'otherGenerators',
    items: [
      { icon: 'fileText', label: 'drafts', href: '/drafts' },
      { icon: 'github', label: 'github', href: '/github' },
      { icon: 'user', label: 'resume', href: '/resume', adminOnly: true },
      { icon: 'sparkles', label: 'generate', href: '/generate' },
    ],
  },
  {
    label: 'quality',
    items: [
      { icon: 'shield', label: 'qualityControl', href: '/quality' },
      { icon: 'copyCheck', label: 'verifyQa', href: '/agent-test' },
      { icon: 'terminal', label: 'prompts', href: '/prompts' },
    ],
  },
  {
    label: 'configuration',
    items: [{ icon: 'cpu', label: 'models', href: '/models' }],
  },
]

// The static sidebar on wide screens; below the drawer breakpoint
// (app-shell.css) the same element slides in over the page while `open`.
export function AppSidebar({
  open,
  onClose,
  ref,
}: {
  open: boolean
  onClose: () => void
  ref?: React.Ref<HTMLElement>
}) {
  const pathname = usePathname() ?? ''
  const t = useTranslations()
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + '/')

  // Published datasets live on Hugging Face, drafts in the app: each badge
  // uses the same query (and cache) as its page, so the counts always agree.
  const { data: localDrafts } = useDatasets()
  const { data: toReview } = useDrafts()
  const { data: hfData, isPending: hfPending, error: hfError } = useHubDatasets()
  const { data: vectorData } = useCollections()
  const draftCount = (localDrafts?.length ?? 0) + (toReview?.drafts.length ?? 0)
  const collectionCount = vectorData?.collections.length ?? 0

  const counts: Record<string, string | undefined> = {
    '/datasets': hfData ? String(hfData.total) : undefined,
    '/collections': collectionCount ? String(collectionCount) : undefined,
    '/drafts': draftCount ? String(draftCount) : undefined,
  }

  // Hugging Face connection status: no token reads as "Off" rather than being
  // hidden, since this is a status row, not a data listing.
  const hfConnected = !hfPending && !hfError
  const hfStatusLabel = hfPending ? '…' : hfConnected ? t('shell.hubConnected') : t('shell.hubOff')

  const { data: user } = useCurrentUser()
  const logoutMutation = useLogout()

  return (
    <aside
      id="app-sidebar"
      ref={ref}
      className={cn('sidebar', open && 'open')}
      aria-label={t('shell.navigation')}
    >
      <div className="sb-brand">
        <div className="sb-logo">
          <Icon name="layers" />
        </div>
        <div style={{ lineHeight: 1.1 }}>
          <div className="sb-name">
            Dataset<span style={{ opacity: 0.5 }}>Gen</span>
          </div>
          <div className="sb-ver">v{pkg.version}</div>
        </div>
        <button
          type="button"
          className="icon-btn sb-close"
          aria-label={t('shell.closeNavigation')}
          onClick={onClose}
        >
          <Icon name="x" />
        </button>
      </div>
      <nav className="sb-scroll">
        {NAV.map((group) => (
          <div className="sb-group" key={group.label}>
            <div className="sb-label">{t(`nav.groups.${group.label}`)}</div>
            {group.items
              .filter((it) => !it.adminOnly || user?.role === 'admin')
              .map((it) => {
                const count = it.href in counts ? counts[it.href] : it.count
                return (
                  <Link
                    key={it.href}
                    href={it.href}
                    className={cn('sb-link', isActive(it.href) && 'active')}
                    onClick={onClose}
                  >
                    <Icon name={it.icon} />
                    <span>{t(`nav.${it.label}`)}</span>
                    {count && <span className="count">{count}</span>}
                  </Link>
                )
              })}
            {/* Real Hugging Face connection status, not a nav destination —
                links out to the account's Hub profile once connected. */}
            {group.label === 'configuration' &&
              (hfConnected && hfData?.namespace ? (
                <a
                  href={`https://huggingface.co/${hfData.namespace}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="sb-link"
                >
                  <Icon name="link" />
                  <span>Hugging Face</span>
                  <span className="count count-success">{hfStatusLabel}</span>
                </a>
              ) : (
                <div className="sb-link" style={{ cursor: 'default', opacity: 0.7 }}>
                  <Icon name="link" />
                  <span>Hugging Face</span>
                  <span className="count">{hfStatusLabel}</span>
                </div>
              ))}
          </div>
        ))}
        {user?.role === 'admin' && (
          <div className="sb-group">
            <div className="sb-label">{t('nav.groups.admin')}</div>
            <Link
              href="/admin"
              className={cn('sb-link', isActive('/admin') && 'active')}
              onClick={onClose}
            >
              <Icon name="shield" />
              <span>{t('nav.backoffice')}</span>
            </Link>
          </div>
        )}
        <div className="sb-group">
          <div className="sb-label">{t('nav.groups.account')}</div>
          <Link
            href="/settings"
            className={cn('sb-link', isActive('/settings') && 'active')}
            onClick={onClose}
          >
            <Icon name="settings" />
            <span>{t('nav.settings')}</span>
          </Link>
          <button type="button" className="sb-link">
            <Icon name="fileText" />
            <span>{t('nav.legalNotice')}</span>
          </button>
        </div>
      </nav>
      <div className="sb-foot">
        {/* Phones only: the top bar has no room for these there. */}
        <div className="sb-tools">
          <ShellTools />
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger className="sb-user">
            <span className="avatar">{initialsFor(user?.name)}</span>
            <span className="meta">
              <span className="nm">{user?.name ?? t('shell.loading')}</span>
              <span className="em">
                {user?.role === 'admin' || user?.role === 'user'
                  ? t(`shell.roles.${user.role}`)
                  : (user?.role ?? '')}
              </span>
            </span>
            <Icon name="chevronDown" className="ic-sm" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" side="top" style={{ width: 220 }}>
            <DropdownMenuItem asChild>
              <Link href="/settings">
                <Icon name="settings" className="ic-sm" />
                {t('nav.settings')}
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              disabled={logoutMutation.isPending}
              onSelect={() => logoutMutation.mutate()}
            >
              <Icon name="logout" className="ic-sm" />
              {t('shell.signOut')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
  )
}
