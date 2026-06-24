'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Icon } from '@/components/app/icon'
import { cn } from '@/lib/utils'

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
      { icon: 'database', label: 'Datasets', href: '/datasets', count: '24' },
      { icon: 'sparkles', label: 'Generation', href: '/generate' },
      { icon: 'globe', label: 'Sources', href: '/sources', count: '11' },
    ],
  },
  {
    label: 'Quality & processing',
    items: [
      { icon: 'shield', label: 'Quality control', href: '/quality' },
      { icon: 'activity', label: 'Jobs & batch', href: '/jobs', count: '3' },
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
  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + '/')

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
          <div className="sb-ver">v0.7.7</div>
        </div>
      </div>
      <nav className="sb-scroll">
        {NAV.map((group) => (
          <div className="sb-group" key={group.label}>
            <div className="sb-label">{group.label}</div>
            {group.items.map((it) => (
              <Link
                key={it.href}
                href={it.href}
                className={cn('sb-link', isActive(it.href) && 'active')}
              >
                <Icon name={it.icon} />
                <span>{it.label}</span>
                {it.count && <span className="count">{it.count}</span>}
              </Link>
            ))}
          </div>
        ))}
        <div className="sb-group">
          <div className="sb-label">Account</div>
          <Link
            href="/settings"
            className={cn('sb-link', isActive('/settings') && 'active')}
          >
            <Icon name="settings" />
            <span>Settings</span>
          </Link>
          <a className="sb-link" href="#">
            <Icon name="fileText" />
            <span>Legal notice</span>
          </a>
        </div>
      </nav>
      <div className="sb-foot">
        <Link className="sb-user" href="/settings">
          <span className="avatar">KB</span>
          <span className="meta">
            <span className="nm">Kévin De Benedetti</span>
            <span className="em">kevin@datasetgen.io</span>
          </span>
          <Icon name="chevronDown" className="ic-sm" />
        </Link>
      </div>
    </aside>
  )
}
