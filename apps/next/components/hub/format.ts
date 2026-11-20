// Display helpers for the Hub viewer: sizes, counts, times and repo ids.
// Each formatter takes the page's language last (`useLocale()`); English when
// it is left out.

import { DEFAULT_LOCALE, type Locale } from '../../i18n/config'

const BYTE_UNITS: Record<Locale, string[]> = {
  en: ['B', 'KB', 'MB', 'GB', 'TB'],
  fr: ['o', 'Ko', 'Mo', 'Go', 'To'],
}

type Formats = {
  full: Intl.NumberFormat
  compact: Intl.NumberFormat
  significant: Intl.NumberFormat
}
const formats = new Map<Locale, Formats>()

function numbers(locale: Locale): Formats {
  let found = formats.get(locale)
  if (!found) {
    found = {
      full: new Intl.NumberFormat(locale),
      compact: new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }),
      significant: new Intl.NumberFormat(locale, { maximumSignificantDigits: 3 }),
    }
    formats.set(locale, found)
  }
  return found
}

/** 512 B / 1.5 KB / 230 MB (512 o / 1,5 Ko / 230 Mo). */
export function formatBytes(
  value: number | null | undefined,
  locale: Locale = DEFAULT_LOCALE,
): string {
  if (value == null || Number.isNaN(value)) return '—'
  const units = BYTE_UNITS[locale]
  if (value < 1024) return `${value} ${units[0]}`
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const size = value / 1024 ** exponent
  const digits = size >= 100 ? 0 : 1
  const shown = new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: false,
  }).format(size)
  return `${shown} ${units[exponent]}`
}

/** 1,284 in full under 10,000; 12.9K / 4.2M above. */
export function formatCount(
  value: number | null | undefined,
  locale: Locale = DEFAULT_LOCALE,
): string {
  if (value == null || Number.isNaN(value)) return '—'
  const { full, compact } = numbers(locale)
  return Math.abs(value) < 10_000 ? full.format(value) : compact.format(value)
}

/** A measured value: whole numbers as counts, others to 3 significant digits. */
export function formatValue(
  value: number | null | undefined,
  locale: Locale = DEFAULT_LOCALE,
): string {
  if (value == null || Number.isNaN(value)) return '—'
  return Number.isInteger(value)
    ? formatCount(value, locale)
    : numbers(locale).significant.format(value)
}

/** Share of a whole, rounded: 0%, <1%, 42% (42 % in French). */
export function formatPercent(
  part: number,
  whole: number,
  locale: Locale = DEFAULT_LOCALE,
): string {
  const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 })
  if (!whole || !part) return percent.format(0)
  const share = part / whole
  return share < 0.01 ? `<${percent.format(0.01)}` : percent.format(share)
}

export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : '—'
}

const JUST_NOW: Record<Locale, string> = { en: 'just now', fr: 'à l’instant' }

/** just now / 5m ago / 3h ago / 2d ago / 3w ago / 4mo ago / 2y ago (à l’instant /
 *  il y a 5 min / il y a 3 h / … / il y a 4 mois / il y a 2 ans). */
export function timeAgo(
  value: string | null | undefined,
  now: number,
  locale: Locale = DEFAULT_LOCALE,
): string {
  if (!value) return '—'
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return '—'
  const minutes = Math.floor(Math.max(0, now - time) / 60_000)
  if (minutes < 1) return JUST_NOW[locale]
  // English keeps its compact form; French reads "il y a 5 min", with months
  // and years spelled out ("il y a 4 m." would be unclear).
  const ago = (amount: number, unit: Intl.RelativeTimeFormatUnit) => {
    const long = locale !== 'en' && (unit === 'month' || unit === 'year')
    const style = locale === 'en' ? 'narrow' : long ? 'long' : 'short'
    return new Intl.RelativeTimeFormat(locale, { style, numeric: 'always' }).format(-amount, unit)
  }
  if (minutes < 60) return ago(minutes, 'minute')
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return ago(hours, 'hour')
  const days = Math.floor(hours / 24)
  if (days < 7) return ago(days, 'day')
  if (days < 35) return ago(Math.floor(days / 7), 'week')
  if (days < 365) return ago(Math.floor(days / 30), 'month')
  return ago(Math.floor(days / 365), 'year')
}

export function formatDateTime(value: string | null | undefined, locale?: Locale): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(locale)
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
