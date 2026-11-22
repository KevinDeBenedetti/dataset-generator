import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { DEFAULT_LOCALE, type Locale } from '../i18n/config'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Two-letter avatar initials derived from the local part of an email address.
export function initialsFor(email: string | undefined | null) {
  const local = email?.split('@')[0] ?? ''
  return local.slice(0, 2).toUpperCase() || '??'
}

// Coarse "time ago" label (today / Nd ago / Nw ago / Nmo ago / Ny ago).
// How "N units ago" reads in each language: English keeps its compact form
// ("5m ago"); French reads "il y a 5 min", with months and years spelled out
// ("il y a 4 m." would be unclear).
const AGO_STYLE: Record<
  Locale,
  (unit: Intl.RelativeTimeFormatUnit) => Intl.RelativeTimeFormatStyle
> = {
  en: () => 'narrow',
  fr: (unit) => (unit === 'month' || unit === 'year' ? 'long' : 'short'),
}

/** "N units ago" in `locale`: 5m ago, il y a 5 min… */
export function ago(amount: number, unit: Intl.RelativeTimeFormatUnit, locale: Locale): string {
  return new Intl.RelativeTimeFormat(locale, {
    style: AGO_STYLE[locale](unit),
    numeric: 'always',
  }).format(-amount, unit)
}

/** "just now" in `locale` (English keeps its own words; others: Intl's). */
export function justNow(locale: Locale): string {
  if (locale === 'en') return 'just now'
  return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(0, 'second')
}

/** today / 3d ago / 2w ago / 4mo ago / 1y ago, day-granular (aujourd’hui /
 *  il y a 3 j / …) in the page's language (`useLocale()`; English if left out). */
export function relativeTime(
  dateStr: string | null | undefined,
  now: number,
  locale: Locale = DEFAULT_LOCALE,
): string {
  if (!dateStr) return '—'
  const t = new Date(dateStr).getTime()
  if (Number.isNaN(t)) return '—'
  const day = 24 * 60 * 60 * 1000
  const diff = now - t
  if (diff < day) {
    return new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(0, 'day')
  }
  const days = Math.floor(diff / day)
  if (days < 7) return ago(days, 'day', locale)
  const weeks = Math.floor(days / 7)
  if (weeks < 5) return ago(weeks, 'week', locale)
  const months = Math.floor(days / 30)
  if (months < 12) return ago(months, 'month', locale)
  return ago(Math.floor(days / 365), 'year', locale)
}

// Flips the `dark` class on <html> and persists the choice.
export function toggleTheme() {
  const next = !document.documentElement.classList.contains('dark')
  document.documentElement.classList.toggle('dark', next)
  try {
    localStorage.setItem('dg-theme', next ? 'dark' : 'light')
  } catch {
    // ignore storage errors (private mode, etc.)
  }
}
