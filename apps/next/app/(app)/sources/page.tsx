'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { Icon } from '@/components/app/icon'
import { useLangfuseDatasets } from '@/hooks'
import { relativeTime } from '@/lib/utils'
import type { LangfuseDataset } from '@/api/sdk'

type SourceGroup = {
  key: string
  label: string
  icon: string
  datasetCount: number
  lastGeneratedAt: string | null
}

// Datasets don't have a first-class "source" of their own — a source is
// derived from the host (or scheme, for file:// / github:// origins) of the
// datasets generated from it. Grouping client-side keeps this in sync with
// the same data the Dashboard/Datasets pages already show, with no new
// backend concept to maintain.
function sourceKeyLabelIcon(sourceUrl: string | null | undefined) {
  if (!sourceUrl) return { key: 'unknown', label: 'Unknown source', icon: 'globe' }
  try {
    const u = new URL(sourceUrl)
    if (u.protocol === 'http:' || u.protocol === 'https:') {
      return { key: u.host, label: u.host, icon: 'globe' }
    }
    if (u.protocol === 'github:') {
      return { key: sourceUrl, label: sourceUrl.replace('github://', ''), icon: 'github' }
    }
    if (u.protocol === 'file:') {
      return { key: sourceUrl, label: sourceUrl.replace('file://', ''), icon: 'fileText' }
    }
    return { key: sourceUrl, label: sourceUrl, icon: 'globe' }
  } catch {
    return { key: sourceUrl, label: sourceUrl, icon: 'globe' }
  }
}

function groupBySource(datasets: LangfuseDataset[]): SourceGroup[] {
  const groups = new Map<string, SourceGroup>()
  for (const d of datasets) {
    const { key, label, icon } = sourceKeyLabelIcon(d.source_url)
    const existing = groups.get(key)
    if (existing) {
      existing.datasetCount += 1
      if (
        d.created_at &&
        (!existing.lastGeneratedAt || d.created_at > existing.lastGeneratedAt)
      ) {
        existing.lastGeneratedAt = d.created_at
      }
    } else {
      groups.set(key, {
        key,
        label,
        icon,
        datasetCount: 1,
        lastGeneratedAt: d.created_at ?? null,
      })
    }
  }
  return [...groups.values()].toSorted(
    (a, b) => b.datasetCount - a.datasetCount || a.label.localeCompare(b.label),
  )
}

export default function SourcesPage() {
  const { data, isLoading, error } = useLangfuseDatasets()
  const [filter, setFilter] = useState('')
  const now = Date.now()

  const sources = useMemo(() => groupBySource(data?.datasets ?? []), [data])
  const filtered = filter.trim()
    ? sources.filter((s) => s.label.toLowerCase().includes(filter.trim().toLowerCase()))
    : sources

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Sources</h1>
          <p className="page-sub">
            Content origins your datasets were generated from.{' '}
            {sources.length > 0 &&
              `${sources.length} connected source${sources.length === 1 ? '' : 's'}.`}
          </p>
        </div>
        <div className="page-actions">
          <Link href="/generate" className="btn btn-primary">
            <Icon name="plus" />
            Add a source
          </Link>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <div className="card-title">All sources</div>
          </div>
          <label className="topbar-search" style={{ display: 'flex', minWidth: 240 }}>
            <Icon name="search" />
            <input
              placeholder="Filter…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </label>
        </div>

        {error ? (
          <div className="card-body">
            <p className="muted">Failed to load sources.</p>
          </div>
        ) : isLoading ? (
          <div className="card-body">
            <p className="muted">Loading sources…</p>
          </div>
        ) : sources.length === 0 ? (
          <div className="card-body">
            <p className="muted">
              No sources yet. <Link href="/generate">Generate a dataset</Link> to connect one.
            </p>
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Linked datasets</th>
                <th>Last generated</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.key}>
                  {/* oxlint-disable-next-line jsx-a11y/control-has-associated-label --
                      false positive: static, non-interactive cell; the icon is
                      already aria-hidden (see Icon) and the cell has visible
                      accessible text (s.label). */}
                  <td>
                    <div className="cell-main">
                      <span className="cell-ic">
                        <Icon name={s.icon} />
                      </span>
                      <div className="cell-title">{s.label}</div>
                    </div>
                  </td>
                  <td className="mono">{s.datasetCount}</td>
                  <td className="muted">{relativeTime(s.lastGeneratedAt, now)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
