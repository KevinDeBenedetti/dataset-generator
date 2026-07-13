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
