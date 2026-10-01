'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { useAdminUsers, useDeleteAdminUser, useUpdateAdminUser } from '@/hooks/use-admin'
import { useCurrentUser } from '@/hooks/use-auth'
import type { AdminUser } from '@/api/sdk'

const PAGE = 50

const fail = (e: Error) => toast.error(e.message)

function when(value?: string | null) {
  return value ? new Date(value).toLocaleDateString() : '—'
}

function UserRow({ user, me }: { user: AdminUser; me?: string }) {
  const update = useUpdateAdminUser()
  const remove = useDeleteAdminUser()
  const busy = update.isPending || remove.isPending
  const self = user.id === me

  return (
    <tr>
      <td>
        <div style={{ fontWeight: 500 }}>{user.email}</div>
        <div className="hint">
          {[...user.providers, user.has_password ? 'password' : null].filter(Boolean).join(' · ') ||
            '—'}
        </div>
      </td>
      <td>
        <span className={`badge badge-${user.role === 'admin' ? 'info' : 'secondary'}`}>
          {user.role}
          {user.locked ? ' · locked' : ''}
        </span>{' '}
        {!user.is_active && <span className="badge badge-destructive">disabled</span>}
      </td>
      <td className="mono">
        {user.datasets} / {user.pairs} / {user.runs}
      </td>
      <td className="hint">{user.configured_keys.join(', ') || '—'}</td>
      <td className="hint">
        {when(user.created_at)} · {when(user.last_login_at)}
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
              {user.role === 'admin' ? 'Make user' : 'Make admin'}
            </button>{' '}
            <button
              className="btn btn-outline btn-sm"
              type="button"
              disabled={busy}
              onClick={() =>
                update.mutate({ id: user.id, is_active: !user.is_active }, { onError: fail })
              }
            >
              {user.is_active ? 'Disable' : 'Enable'}
            </button>{' '}
            {!self && (
              <button
                className="btn btn-outline btn-sm"
                type="button"
                disabled={busy}
                onClick={() => {
                  if (
                    window.confirm(
                      `Delete ${user.email} and everything they own? Their Hugging Face repos are not touched.`,
                    )
                  ) {
                    remove.mutate(user.id, {
                      onSuccess: () => toast.success(`${user.email} deleted`),
                      onError: fail,
                    })
                  }
                }}
              >
                Delete
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

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Users</div>
          <div className="card-desc">
            Datasets / pairs / runs are counts only. Locked accounts are listed in ADMIN_EMAILS.
          </div>
        </div>
        <input
          className="input"
          style={{ maxWidth: 260 }}
          placeholder="Search by email"
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setOffset(0)
          }}
        />
      </div>
      <div className="card-body" style={{ overflowX: 'auto' }}>
        {error && <p className="hint">{error.message}</p>}
        <table className="table" style={{ width: '100%' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left' }}>Account</th>
              <th style={{ textAlign: 'left' }}>Role</th>
              <th style={{ textAlign: 'left' }}>Data</th>
              <th style={{ textAlign: 'left' }}>Keys saved</th>
              <th style={{ textAlign: 'left' }}>Created · last sign-in</th>
              <th aria-label="Actions" />
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
            Previous
          </button>
          <span className="hint">
            {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
          </span>
          <button
            className="btn btn-outline btn-sm"
            type="button"
            disabled={offset + PAGE >= data.total}
            onClick={() => setOffset(offset + PAGE)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
