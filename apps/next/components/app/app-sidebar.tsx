'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Icon } from '@/components/app/icon'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useDatasets, useHuggingFaceDatasets } from '@/hooks'
import { useCurrentUser, useLogout } from '@/hooks/use-auth'
import { cn, initialsFor } from '@/lib/utils'
import pkg from '@/package.json'

type NavItem = {
  icon: string
  label: string
  href: string
  count?: string
}

const NAV: { label: string; items: NavItem[] }[] = [
  {
    label: 'Platform',
    items: [
      { icon: 'dashboard', label: 'Overview', href: '/dashboard' },
      { icon: 'database', label: 'Datasets', href: '/datasets' },
      { icon: 'sparkles', label: 'Generation', href: '/generate' },
    ],
  },
  {
    label: 'Quality & processing',
    items: [
      { icon: 'shield', label: 'Quality control', href: '/quality' },
      { icon: 'activity', label: 'Jobs & batch', href: '/jobs' },
      { icon: 'copyCheck', label: 'Verify QA', href: '/agent-test' },
      { icon: 'terminal', label: 'LLM Prompts', href: '/prompts' },
    ],
  },
  {
    label: 'Delivery',
    items: [
      { icon: 'download', label: 'Exports', href: '/exports' },
      { icon: 'key', label: 'API keys & integrations', href: '/api-keys' },
    ],
  },
]

export function AppSidebar() {
  const pathname = usePathname() ?? ''
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + '/')

  // Real dataset count for the Datasets nav badge. Uses the same source as the
  // /datasets page so the badge matches what's listed there; the
  // shared react-query cache means no extra request.
  const { data: datasets } = useDatasets()
  const datasetCount = datasets?.length

  const counts: Record<string, string | undefined> = {
    '/datasets': datasetCount != null ? String(datasetCount) : undefined,
  }

  // Real Hugging Face connection status for the "Delivery" group — same query
  // (and cache) the /datasets page and dashboard already use. No HF_TOKEN
  // configured surfaces as an error there, which here reads as "Off" rather
  // than being hidden, since this is a status row, not a data listing.
  const { data: hfData, isPending: hfPending, error: hfError } = useHuggingFaceDatasets()
  const hfConnected = !hfPending && !hfError
  const hfStatusLabel = hfPending ? '…' : hfConnected ? `${hfData?.total ?? 0} synced` : 'Off'

  const { data: user } = useCurrentUser()
  const logoutMutation = useLogout()

  return (
    <aside className="sidebar">
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
      </div>
      <nav className="sb-scroll">
        {NAV.map((group) => (
          <div className="sb-group" key={group.label}>
            <div className="sb-label">{group.label}</div>
            {group.items.map((it) => {
              const count = it.href in counts ? counts[it.href] : it.count
              return (
                <Link
                  key={it.href}
                  href={it.href}
                  className={cn('sb-link', isActive(it.href) && 'active')}
                >
                  <Icon name={it.icon} />
                  <span>{it.label}</span>
                  {count && <span className="count">{count}</span>}
                </Link>
              )
            })}
            {/* Real Hugging Face connection status, not a nav destination —
                links out to the account's Hub profile once connected. */}
            {group.label === 'Delivery' &&
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
        <div className="sb-group">
          <div className="sb-label">Account</div>
          <Link href="/settings" className={cn('sb-link', isActive('/settings') && 'active')}>
            <Icon name="settings" />
            <span>Settings</span>
          </Link>
          <button type="button" className="sb-link">
            <Icon name="fileText" />
            <span>Legal notice</span>
          </button>
        </div>
      </nav>
      <div className="sb-foot">
        <DropdownMenu>
          <DropdownMenuTrigger className="sb-user">
            <span className="avatar">{initialsFor(user?.email)}</span>
            <span className="meta">
              <span className="nm">{user?.email ?? 'Loading…'}</span>
              <span className="em">{user?.role ?? ''}</span>
            </span>
            <Icon name="chevronDown" className="ic-sm" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" side="top" style={{ width: 220 }}>
            <DropdownMenuItem asChild>
              <Link href="/settings">
                <Icon name="settings" className="ic-sm" />
                Settings
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              disabled={logoutMutation.isPending}
              onSelect={() => logoutMutation.mutate()}
            >
              <Icon name="logout" className="ic-sm" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </aside>
  )
}
