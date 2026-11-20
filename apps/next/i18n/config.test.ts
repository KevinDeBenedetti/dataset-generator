import { describe, expect, it } from 'vitest'
import { localeCookie, pickLocale } from './config'

describe('pickLocale', () => {
  it('keeps the language the reader picked', () => {
    expect(pickLocale('fr', 'en-US,en;q=0.9')).toBe('fr')
    expect(pickLocale('en', 'fr-FR')).toBe('en')
  })

  it("falls back to the browser's languages, best first", () => {
    expect(pickLocale(undefined, 'fr-CA,fr;q=0.9,en;q=0.8')).toBe('fr')
    expect(pickLocale(undefined, 'de;q=0.9,fr;q=0.4,en;q=0.7')).toBe('en')
    expect(pickLocale(undefined, 'en;q=0,fr;q=0.1')).toBe('fr')
  })

  it('is English for anything else', () => {
    expect(pickLocale(undefined, undefined)).toBe('en')
    expect(pickLocale('de', 'es-ES,de;q=0.8')).toBe('en')
    expect(pickLocale('fr; Path=/evil', '')).toBe('en')
  })
})

describe('localeCookie', () => {
  it('is a year-long, site-wide cookie', () => {
    expect(localeCookie('fr', false)).toBe('dg-locale=fr; Path=/; Max-Age=31536000; SameSite=Lax')
    expect(localeCookie('en', true)).toMatch(/; Secure$/)
  })
})
