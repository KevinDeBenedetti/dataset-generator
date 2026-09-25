'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { Icon } from '@/components/app/icon'
import { useAllDatasetSources, type DatasetSourceRow } from '@/hooks'
import { relativeTime } from '@/lib/utils'

type SourceGroup = {
  key: string
  label: string
  icon: string
  datasets: Set<string>
  qaCount: number
  lastGeneratedAt: string | null
}

const KIND_ICON: Record<string, string> = {
  web: 'globe',
  file: 'fileText',
  github: 'github',
  unknown: 'help',
}

// Sources are recorded per page/file/account, so a crawl of 50 pages yields 50
// rows. Grouping them by origin (the host, for web sources) is what makes the
// list readable: one row per site, file or account, whatever the number of
// pages behind it.
function groupKey(source: DatasetSourceRow): { key: string; label: string } {
  if (source.kind === 'web' && source.url) {
    try {
      const { host } = new URL(source.url)
      return { key: host, label: host }
    } catch {
      return { key: source.label, label: source.label }
    }
  }
  return { key: source.label, label: source.label }
}

function groupBySource(sources: DatasetSourceRow[]): SourceGroup[] {
  const groups = new Map<string, SourceGroup>()
  for (const source of sources) {
    const { key, label } = groupKey(source)
    const existing = groups.get(key)
    if (existing) {
      existing.datasets.add(source.dataset)
      existing.qaCount += source.qa_count
      if (
        source.last_seen_at &&
        (!existing.lastGeneratedAt || source.last_seen_at > existing.lastGeneratedAt)
      ) {
        existing.lastGeneratedAt = source.last_seen_at
      }
    } else {
      groups.set(key, {
        key,
        label,
        icon: KIND_ICON[source.kind] ?? 'globe',
        datasets: new Set([source.dataset]),
        qaCount: source.qa_count,
        lastGeneratedAt: source.last_seen_at ?? null,
      })
    }
  }
  return [...groups.values()].toSorted(
    (a, b) => b.qaCount - a.qaCount || a.label.localeCompare(b.label),
  )
}

export default function SourcesPage() {
  const { data, isPending, error } = useAllDatasetSources()
  const [filter, setFilter] = useState('')
  const now = Date.now()

  const sources = useMemo(() => groupBySource(data ?? []), [data])
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
        ) : isPending ? (
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
                <th>Q/A pairs</th>
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
                  <td className="mono">{s.qaCount}</td>
                  <td className="mono">{s.datasets.size}</td>
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
