'use client'

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { useAdminUsers, useDeleteAdminUser, useUpdateAdminUser } from '@/hooks/use-admin'
import { useCurrentUser } from '@/hooks/use-auth'
import type { AdminUser } from '@/api/sdk'

const PAGE = 50

const fail = (e: Error) => toast.error(e.message)

function when(locale: string, value?: string | null) {
  return value ? new Date(value).toLocaleDateString(locale) : '—'
}

function UserRow({ user, me }: { user: AdminUser; me?: string }) {
  const update = useUpdateAdminUser()
  const remove = useDeleteAdminUser()
  const busy = update.isPending || remove.isPending
  const self = user.id === me
  const t = useTranslations('admin.users')
  const tc = useTranslations('common')
  const locale = useLocale()

  return (
    <tr>
      <td data-label={t('account')}>
        <div style={{ fontWeight: 500 }}>{user.email}</div>
        <div className="hint">
          {[...user.providers, user.has_password ? t('password') : null]
            .filter(Boolean)
            .join(' · ') || '—'}
        </div>
      </td>
      <td data-label={t('role')}>
        <span className={`badge badge-${user.role === 'admin' ? 'info' : 'secondary'}`}>
          {user.role === 'admin' || user.role === 'user' ? t(`roles.${user.role}`) : user.role}
          {user.locked ? ` · ${t('locked')}` : ''}
        </span>{' '}
        {!user.is_active && <span className="badge badge-destructive">{t('disabled')}</span>}
      </td>
      <td className="mono" data-label={t('data')}>
        {user.datasets} / {user.pairs} / {user.runs}
      </td>
      <td className="hint" data-label={t('keys')}>
        {user.configured_keys.join(', ') || '—'}
      </td>
      <td className="hint" data-label={t('dates')}>
        {when(locale, user.created_at)} · {when(locale, user.last_login_at)}
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
        {!user.locked && (
          <>
            <button
              className="btn btn-outline btn-sm"
              type="button"
              disabled={busy}
              onClick={() =>
                update.mutate(
                  { id: user.id, role: user.role === 'admin' ? 'user' : 'admin' },
                  { onError: fail },
                )
              }
            >
              {user.role === 'admin' ? t('makeUser') : t('makeAdmin')}
            </button>{' '}
            <button
              className="btn btn-outline btn-sm"
              type="button"
              disabled={busy}
              onClick={() =>
                update.mutate({ id: user.id, is_active: !user.is_active }, { onError: fail })
              }
            >
              {user.is_active ? t('disable') : t('enable')}
            </button>{' '}
            {!self && (
              <button
                className="btn btn-outline btn-sm"
                type="button"
                disabled={busy}
                onClick={() => {
                  if (window.confirm(t('confirmDelete', { email: user.email }))) {
                    remove.mutate(user.id, {
                      onSuccess: () => toast.success(t('deleted', { email: user.email })),
                      onError: fail,
                    })
                  }
                }}
              >
                {tc('delete')}
              </button>
            )}
          </>
        )}
      </td>
    </tr>
  )
}

export default function AdminUsersPage() {
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, error } = useAdminUsers(q, offset)
  const { data: me } = useCurrentUser()
  const t = useTranslations('admin.users')
  const tc = useTranslations('common')

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{t('title')}</div>
          <div className="card-desc">{t('description')}</div>
        </div>
        <input
          className="input"
          style={{ maxWidth: 260 }}
          placeholder={t('search')}
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setOffset(0)
          }}
        />
      </div>
      <div className="card-body" style={{ overflowX: 'auto' }}>
        {error && <p className="hint">{error.message}</p>}
        <table className="table stack-table" style={{ width: '100%' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left' }}>{t('account')}</th>
              <th style={{ textAlign: 'left' }}>{t('role')}</th>
              <th style={{ textAlign: 'left' }}>{t('data')}</th>
              <th style={{ textAlign: 'left' }}>{t('keys')}</th>
              <th style={{ textAlign: 'left' }}>{t('dates')}</th>
              <th aria-label={t('actions')} />
            </tr>
          </thead>
          <tbody>
            {(data?.users ?? []).map((user) => (
              <UserRow key={user.id} user={user} me={me?.id} />
            ))}
          </tbody>
        </table>
      </div>
      {data && data.total > PAGE && (
        <div className="card-foot" style={{ gap: 8 }}>
          <button
            className="btn btn-outline btn-sm"
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
          >
            {tc('previous')}
          </button>
          <span className="hint">
            {t('range', {
              first: offset + 1,
              last: Math.min(offset + PAGE, data.total),
              total: data.total,
            })}
          </span>
          <button
            className="btn btn-outline btn-sm"
            type="button"
            disabled={offset + PAGE >= data.total}
            onClick={() => setOffset(offset + PAGE)}
          >
            {tc('next')}
          </button>
        </div>
      )}
    </div>
  )
}
