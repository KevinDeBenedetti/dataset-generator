'use client'

import { useMemo } from 'react'
import type { HubDatasetDetail } from '@/api/types'
import { Icon } from '@/components/app/icon'
import { formatBytes, formatCount, shortSha } from './format'

/** Every file of the repo at the commit shown, and the table each one feeds. */
export function FilesPanel({ detail }: { detail: HubDatasetDetail }) {
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
          <div className="card-title">Files</div>
          <div className="card-desc">
            {formatCount(files.length)} file(s), {formatBytes(total)}, at commit{' '}
            <span className="mono">{shortSha(detail.sha)}</span>
          </div>
        </div>
        <a
          className="btn btn-outline btn-sm"
          href={`${detail.url}/tree/${detail.sha}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <Icon name="external" />
          Browse on Hugging Face
        </a>
      </div>
      <div className="hub-table-wrap">
        <table className="table stack-table">
          <thead>
            <tr>
              <th>Path</th>
              <th>Used by</th>
              <th className="num">Size</th>
              <th>
                <span className="sr-only">Open</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {files.map((file) => {
              const slash = file.path.lastIndexOf('/')
              const used = usage.get(file.path)
              return (
                <tr key={file.path}>
                  <td className="mono hub-path" data-label="Path">
                    {slash > 0 && <span className="muted">{file.path.slice(0, slash + 1)}</span>}
                    {file.path.slice(slash + 1)}
                    {file.lfs && <span className="tag hub-lfs">LFS</span>}
                  </td>
                  <td data-label="Used by">
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
                  <td className="num mono" data-label="Size">
                    {formatBytes(file.size)}
                  </td>
                  <td className="num">
                    <a
                      className="icon-btn"
                      href={`${detail.url}/blob/${detail.sha}/${file.path.split('/').map(encodeURIComponent).join('/')}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Open ${file.path} on Hugging Face`}
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
