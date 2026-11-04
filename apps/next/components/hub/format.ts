// Display helpers for the Hub viewer: sizes, counts, times and repo ids.

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

/** 512 B / 1.5 KB / 230 MB. */
export function formatBytes(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  if (value < 1024) return `${value} B`
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), BYTE_UNITS.length - 1)
  const size = value / 1024 ** exponent
  return `${size >= 100 ? size.toFixed(0) : size.toFixed(1)} ${BYTE_UNITS[exponent]}`
}

const FULL = new Intl.NumberFormat('en')
const COMPACT = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })
const SIGNIFICANT = new Intl.NumberFormat('en', { maximumSignificantDigits: 3 })

/** 1,284 in full under 10,000; 12.9K / 4.2M above. */
export function formatCount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return Math.abs(value) < 10_000 ? FULL.format(value) : COMPACT.format(value)
}

/** A measured value: whole numbers as counts, others to 3 significant digits. */
export function formatValue(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return Number.isInteger(value) ? formatCount(value) : SIGNIFICANT.format(value)
}

/** Share of a whole, rounded: 0%, <1%, 42%. */
export function formatPercent(part: number, whole: number): string {
  if (!whole || !part) return '0%'
  const percent = (part / whole) * 100
  return percent < 1 ? '<1%' : `${Math.round(percent)}%`
}

export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : '—'
}

/** just now / 5m ago / 3h ago / 2d ago / 3w ago / 4mo ago / 2y ago. */
export function timeAgo(value: string | null | undefined, now: number): string {
  if (!value) return '—'
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return '—'
  const minutes = Math.floor(Math.max(0, now - time) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  if (days < 35) return `${Math.floor(days / 7)}w ago`
  if (days < 365) return `${Math.floor(days / 30)}mo ago`
  return `${Math.floor(days / 365)}y ago`
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

export function isHttpUrl(value: unknown): value is string {
  return typeof value === 'string' && /^https?:\/\/\S+$/i.test(value)
}

/** One-line JSON for a nested value shown in a cell. */
export function compactJson(value: unknown): string {
  try {
    return JSON.stringify(value) ?? String(value)
  } catch {
    return String(value)
  }
}

/** `owner/name` → `{ owner, name }`. */
export function splitRepoId(id: string): { owner: string; name: string } {
  const slash = id.indexOf('/')
  return slash < 0
    ? { owner: '', name: id }
    : { owner: id.slice(0, slash), name: id.slice(slash + 1) }
}

/** The app page of a Hub dataset. */
export function datasetHref(id: string): string {
  const { owner, name } = splitRepoId(id)
  return `/datasets/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
}
