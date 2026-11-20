'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { useCurrentUser } from '@/hooks/use-auth'
import { cn } from '@/lib/utils'

// `label` is a key of `admin.tabs`.
const TABS = [
  { href: '/admin', label: 'overview' },
  { href: '/admin/users', label: 'users' },
  { href: '/admin/audit', label: 'audit' },
  { href: '/admin/platform', label: 'platform' },
] as const

export function AdminTabs() {
  const pathname = usePathname() ?? ''
  const t = useTranslations('admin.tabs')
  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 18, flexWrap: 'wrap' }}>
      {TABS.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          className={cn('btn btn-sm', pathname === tab.href ? 'btn-primary' : 'btn-outline')}
        >
          {t(tab.label)}
        </Link>
      ))}
    </div>
  )
}

export function AdminGuard({ children }: { children: React.ReactNode }) {
  const { data: user, isPending } = useCurrentUser()
  const t = useTranslations('admin')
  const tc = useTranslations('common')
  if (isPending) return <p className="muted">{tc('loading')}</p>
  if (user?.role !== 'admin') return <p className="muted">{t('guard')}</p>
  return <>{children}</>
}
