'use client'

import { useMemo } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import type { HubDatasetDetail } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatBytes, formatCount, shortSha } from './format'
import { rich } from '@/lib/rich'

/** Every file of the repo at the commit shown, and the table each one feeds. */
export function FilesPanel({ detail }: { detail: HubDatasetDetail }) {
  const t = useTranslations('viewer')
  const tc = useTranslations('common')
  const locale = useLocale()
  const usage = useMemo(() => {
    const map = new Map<string, string[]>()
    for (const view of detail.views) {
      for (const path of view.files) {
        const label = view.config === 'default' ? view.split : `${view.config}/${view.split}`
        map.set(path, [...(map.get(path) ?? []), label])
      }
    }
    return map
  }, [detail.views])

  const files = useMemo(
    () => detail.files.toSorted((a, b) => a.path.localeCompare(b.path)),
    [detail.files],
  )
  const total = files.reduce((sum, f) => sum + (f.size ?? 0), 0)

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{t('files.title')}</div>
          <div className="card-desc">
            {t.rich('files.summary', {
              count: files.length,
              formatted: formatCount(files.length, locale),
              size: formatBytes(total, locale),
              sha: shortSha(detail.sha),
              mono: rich.mono,
            })}
          </div>
        </div>
        <a
          className="btn btn-outline btn-sm"
          href={`${detail.url}/tree/${detail.sha}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <Icon name="external" />
          {t('files.browse')}
        </a>
      </div>
      <div className="hub-table-wrap">
        <table className="table stack-table">
          <thead>
            <tr>
              <th>{t('files.path')}</th>
              <th>{t('files.usedBy')}</th>
              <th className="num">{t('files.size')}</th>
              <th>
                <span className="sr-only">{tc('open')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {files.map((file) => {
              const slash = file.path.lastIndexOf('/')
              const used = usage.get(file.path)
              return (
                <tr key={file.path}>
                  <td className="mono hub-path" data-label={t('files.path')}>
                    {slash > 0 && <span className="muted">{file.path.slice(0, slash + 1)}</span>}
                    {file.path.slice(slash + 1)}
                    {file.lfs && <span className="tag hub-lfs">LFS</span>}
                  </td>
                  <td data-label={t('files.usedBy')}>
                    {used ? (
                      <span className="hub-chips">
                        {used.map((label) => (
                          <span key={label} className="tag">
                            {label}
                          </span>
                        ))}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="num mono" data-label={t('files.size')}>
                    {formatBytes(file.size, locale)}
                  </td>
                  <td className="num">
                    <a
                      className="icon-btn"
                      href={`${detail.url}/blob/${detail.sha}/${file.path.split('/').map(encodeURIComponent).join('/')}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={t('files.openFile', { path: file.path })}
                    >
                      <Icon name="external" />
                    </a>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
