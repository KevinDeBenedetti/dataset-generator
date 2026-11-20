'use client'

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useAuditLog } from '@/hooks/use-admin'

const PAGE = 100

export default function AdminAuditPage() {
  const [offset, setOffset] = useState(0)
  const [action, setAction] = useState('')
  const { data, error } = useAuditLog(offset, action)
  const t = useTranslations('admin.audit')
  const locale = useLocale()

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{t('title')}</div>
          <div className="card-desc">{t('description')}</div>
        </div>
        <input
          className="input mono"
          style={{ maxWidth: 220 }}
          placeholder={t('filter')}
          value={action}
          onChange={(e) => {
            setAction(e.target.value.trim())
            setOffset(0)
          }}
        />
      </div>
      <div className="card-body" style={{ overflowX: 'auto' }}>
        {error && <p className="hint">{error.message}</p>}
        <table className="table stack-table" style={{ width: '100%' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left' }}>{t('when')}</th>
              <th style={{ textAlign: 'left' }}>{t('action')}</th>
              <th style={{ textAlign: 'left' }}>{t('by')}</th>
              <th style={{ textAlign: 'left' }}>{t('on')}</th>
              <th style={{ textAlign: 'left' }}>{t('detail')}</th>
            </tr>
          </thead>
          <tbody>
            {(data?.entries ?? []).map((entry) => (
              <tr key={entry.id}>
                <td className="hint" data-label={t('when')}>
                  {new Date(entry.created_at).toLocaleString(locale)}
                </td>
                <td className="mono" data-label={t('action')}>
                  {entry.action}
                </td>
                <td data-label={t('by')}>{entry.actor ?? '—'}</td>
                <td data-label={t('on')}>{entry.target ?? '—'}</td>
                <td className="mono hint" data-label={t('detail')}>
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
            {t('newer')}
          </button>
          <button
            className="btn btn-outline btn-sm"
            type="button"
            disabled={offset + PAGE >= data.total}
            onClick={() => setOffset(offset + PAGE)}
          >
            {t('older')}
          </button>
        </div>
      )}
    </div>
  )
}
