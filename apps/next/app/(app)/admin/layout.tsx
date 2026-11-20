import { cookies } from 'next/headers'
import { notFound } from 'next/navigation'
import { getTranslations } from 'next-intl/server'
import { AdminGuard, AdminTabs } from '@/components/admin/admin-shell'

// Where the server-side check reaches the API (inside the cluster / compose).
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || 'http://localhost:8000'

// UX only — the API refuses every /admin call from a non-admin anyway. A
// signed-in non-admin gets a plain 404 here; an expired access token (the
// browser will refresh it) falls back to the client-side guard.
async function serverRole(): Promise<'admin' | 'user' | 'unknown'> {
  const jar = await cookies()
  try {
    const response = await fetch(`${API_INTERNAL_URL}/auth/me`, {
      headers: { cookie: jar.toString() },
      cache: 'no-store',
    })
    if (response.status !== 200) return 'unknown'
    const user = (await response.json()) as { role?: string }
    return user.role === 'admin' ? 'admin' : 'user'
  } catch {
    return 'unknown'
  }
}

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const role = await serverRole()
  if (role === 'user') notFound()
  const t = await getTranslations('admin')
  return (
    <AdminGuard>
      <div className="page-head">
        <div>
          <h1 className="page-title">{t('title')}</h1>
          <p className="page-sub">{t('subtitle')}</p>
        </div>
      </div>
      <AdminTabs />
      {children}
    </AdminGuard>
  )
}
