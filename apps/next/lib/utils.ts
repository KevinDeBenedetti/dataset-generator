import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Two-letter avatar initials derived from the local part of an email address.
export function initialsFor(email: string | undefined | null) {
  const local = email?.split('@')[0] ?? ''
  return local.slice(0, 2).toUpperCase() || '??'
}

// Coarse "time ago" label (today / Nd ago / Nw ago / Nmo ago / Ny ago).
export function relativeTime(dateStr: string | null | undefined, now: number): string {
  if (!dateStr) return '—'
  const t = new Date(dateStr).getTime()
  if (Number.isNaN(t)) return '—'
  const diff = now - t
  const day = 24 * 60 * 60 * 1000
  if (diff < day) return 'today'
  const days = Math.floor(diff / day)
  if (days < 7) return `${days}d ago`
  const weeks = Math.floor(days / 7)
  if (weeks < 5) return `${weeks}w ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.floor(days / 365)}y ago`
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
