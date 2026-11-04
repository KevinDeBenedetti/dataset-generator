'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { formatCount, formatPercent, formatValue } from './format'

// Single-series charts for the dataset statistics: a column histogram and a
// ranked bar list. One color (--viz-1, see hub.css), no legend (the card's
// title names the series), thin marks with rounded data-ends and 2px gaps.
// Every value is reachable without hovering: the bar list prints its values,
// and a histogram has a table view (``HistogramTable``).

export interface Bin {
  start: number
  end: number
  count: number
}

function binLabel(bin: Bin, integer: boolean): string {
  if (integer && bin.end - bin.start <= 1) return formatValue(bin.start)
  return `${formatValue(bin.start)} – ${formatValue(bin.end)}`
}

export function Histogram({
  bins,
  label,
  unit,
  integer = false,
}: {
  bins: Bin[]
  /** What the bars count, for screen readers ("Characters per value"). */
  label: string
  /** Unit of the x axis, after the edge values ("chars"). */
  unit?: string
  integer?: boolean
}) {
  const [active, setActive] = useState<number | null>(null)
  if (bins.length === 0) return null
  const max = Math.max(1, ...bins.map((b) => b.count))
  const total = bins.reduce((sum, b) => sum + b.count, 0)
  const activeBin = active == null ? null : bins[active]
  const first = bins[0]
  const last = bins[bins.length - 1]

  return (
    <figure className="viz-hist">
      <figcaption className="sr-only">{label}</figcaption>
      <div className="viz-hist-plot">
        {bins.map((bin, index) => (
          <button
            type="button"
            key={`${bin.start}-${bin.end}`}
            className={cn('viz-col', active === index && 'active')}
            aria-label={`${binLabel(bin, integer)}${unit ? ` ${unit}` : ''}: ${formatCount(bin.count)} (${formatPercent(bin.count, total)})`}
            onPointerEnter={() => setActive(index)}
            onPointerLeave={() => setActive(null)}
            onFocus={() => setActive(index)}
            onBlur={() => setActive(null)}
          >
            {bin.count > 0 && (
              <span
                className="viz-col-bar"
                style={{ height: `max(2px, ${(bin.count / max) * 100}%)` }}
              />
            )}
          </button>
        ))}
        {activeBin && active != null && (
          <output className="viz-tip" style={{ left: `${((active + 0.5) / bins.length) * 100}%` }}>
            <strong>{formatCount(activeBin.count)}</strong>
            <span>{formatPercent(activeBin.count, total)}</span>
            <span className="viz-tip-label">
              {binLabel(activeBin, integer)}
              {unit ? ` ${unit}` : ''}
            </span>
          </output>
        )}
      </div>
      <div className="viz-axis" aria-hidden="true">
        <span>{formatValue(first.start)}</span>
        <span>
          {formatValue(last.end)}
          {unit ? ` ${unit}` : ''}
        </span>
      </div>
    </figure>
  )
}

/** The table view of a histogram: every bin, its count and its share. */
export function HistogramTable({
  bins,
  unit,
  integer = false,
}: {
  bins: Bin[]
  unit?: string
  integer?: boolean
}) {
  const total = bins.reduce((sum, b) => sum + b.count, 0)
  return (
    <table className="table viz-table">
      <thead>
        <tr>
          <th>Range{unit ? ` (${unit})` : ''}</th>
          <th className="num">Rows</th>
          <th className="num">Share</th>
        </tr>
      </thead>
      <tbody>
        {bins.map((bin) => (
          <tr key={`${bin.start}-${bin.end}`}>
            <td className="mono">{binLabel(bin, integer)}</td>
            <td className="num mono">{formatCount(bin.count)}</td>
            <td className="num mono">{formatPercent(bin.count, total)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export interface BarItem {
  key: string
  label: string
  count: number
}

/**
 * Ranked values with their counts and shares, as a list of rows. With
 * ``onSelect`` each row is a button (filter the data on that value).
 */
export function BarList({
  items,
  total,
  label,
  onSelect,
  selectHint,
}: {
  items: BarItem[]
  total: number
  label: string
  onSelect?: (key: string) => void
  selectHint?: string
}) {
  const max = Math.max(1, ...items.map((item) => item.count))
  return (
    <ul className="viz-bars" aria-label={label}>
      {items.map((item) => {
        const body = (
          <>
            <span className="viz-bar-label" title={item.label}>
              {item.label}
            </span>
            <span className="viz-bar-track" aria-hidden="true">
              {item.count > 0 && (
                <span
                  className="viz-bar-fill"
                  style={{ width: `max(2px, ${(item.count / max) * 100}%)` }}
                />
              )}
            </span>
            <span className="viz-bar-value">{formatCount(item.count)}</span>
            <span className="viz-bar-share">{formatPercent(item.count, total)}</span>
          </>
        )
        return (
          <li key={item.key}>
            {onSelect ? (
              <button
                type="button"
                className="viz-bar-row"
                onClick={() => onSelect(item.key)}
                title={selectHint}
              >
                {body}
              </button>
            ) : (
              <div className="viz-bar-row">{body}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/** A tiny histogram for a column header: decoration only (aria-hidden); the
 * statistics tab holds the readable version. */
export function MiniHistogram({ bins }: { bins: Bin[] }) {
  if (bins.length === 0) return null
  const max = Math.max(1, ...bins.map((b) => b.count))
  return (
    <span className="viz-mini" aria-hidden="true">
      {bins.map((bin) => (
        <span key={`${bin.start}-${bin.end}`} className="viz-mini-col">
          {bin.count > 0 && <span style={{ height: `max(1px, ${(bin.count / max) * 100}%)` }} />}
        </span>
      ))}
    </span>
  )
}
