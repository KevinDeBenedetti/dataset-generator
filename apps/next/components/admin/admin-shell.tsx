'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useCurrentUser } from '@/hooks/use-auth'
import { cn } from '@/lib/utils'

const TABS = [
  { href: '/admin', label: 'Overview' },
  { href: '/admin/users', label: 'Users' },
  { href: '/admin/audit', label: 'Audit log' },
  { href: '/admin/platform', label: 'Platform' },
]

export function AdminTabs() {
  const pathname = usePathname() ?? ''
  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 18, flexWrap: 'wrap' }}>
      {TABS.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          className={cn('btn btn-sm', pathname === tab.href ? 'btn-primary' : 'btn-outline')}
        >
          {tab.label}
        </Link>
      ))}
    </div>
  )
}

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const { data: user, isPending } = useCurrentUser()
  if (isPending) return <p className="muted">Loading…</p>
  if (user?.role !== 'admin') return <p className="muted">This page is for administrators.</p>
  return <>{children}</>
}
