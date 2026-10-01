'use client'

import { useState } from 'react'
import { useAuditLog } from '@/hooks/use-admin'

const PAGE = 100

export default function AdminAuditPage() {
  const [offset, setOffset] = useState(0)
  const [action, setAction] = useState('')
  const { data, error } = useAuditLog(offset, action)

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Audit log</div>
          <div className="card-desc">
            Security events. Deleted accounts appear as a short hash of their email.
          </div>
        </div>
        <input
          className="input mono"
          style={{ maxWidth: 220 }}
          placeholder="Filter: e.g. user.signup"
          value={action}
          onChange={(e) => {
            setAction(e.target.value.trim())
            setOffset(0)
          }}
        />
      </div>
      <div className="card-body" style={{ overflowX: 'auto' }}>
        {error && <p className="hint">{error.message}</p>}
        <table className="table" style={{ width: '100%' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left' }}>When</th>
              <th style={{ textAlign: 'left' }}>Action</th>
              <th style={{ textAlign: 'left' }}>By</th>
              <th style={{ textAlign: 'left' }}>On</th>
              <th style={{ textAlign: 'left' }}>Detail</th>
            </tr>
          </thead>
          <tbody>
            {(data?.entries ?? []).map((entry) => (
              <tr key={entry.id}>
                <td className="hint">{new Date(entry.created_at).toLocaleString()}</td>
                <td className="mono">{entry.action}</td>
                <td>{entry.actor ?? '—'}</td>
                <td>{entry.target ?? '—'}</td>
                <td className="mono hint">
                  {Object.keys(entry.detail).length ? JSON.stringify(entry.detail) : ''}
                  {entry.ip ? ` · ${entry.ip}` : ''}
                </td>
              </tr>
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
            Newer
          </button>
          <button
            className="btn btn-outline btn-sm"
            type="button"
            disabled={offset + PAGE >= data.total}
            onClick={() => setOffset(offset + PAGE)}
          >
            Older
          </button>
        </div>
      )}
    </div>
  )
}
