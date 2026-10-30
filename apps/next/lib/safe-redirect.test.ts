import { describe, expect, it } from 'vitest'
import { safeRedirectPath } from './safe-redirect'

const ORIGIN = 'https://app.example.com'

describe('safeRedirectPath', () => {
  it('keeps a path on the same origin, with its query and hash', () => {
    expect(safeRedirectPath('/datasets/a?tab=qa#top', ORIGIN)).toBe('/datasets/a?tab=qa#top')
  })

  it('resolves dot segments that stay on the origin', () => {
    expect(safeRedirectPath('/datasets/../settings', ORIGIN)).toBe('/settings')
  })

  it.each([
    ['protocol-relative', '//evil.example'],
    ['backslash', '/\\evil.example'],
    ['tab', '/\t/evil.example'],
    ['newline', '/\n/evil.example'],
    ['absolute', 'https://evil.example/dashboard'],
    ['javascript', 'javascript:alert(1)'],
    // Dot segments resolve away and leave a `//host` path behind.
    ['parent-segment', '/..//evil.example'],
    ['current-segment', '/.//evil.example'],
    ['encoded parent-segment', '/%2e%2e//evil.example'],
    ['dot-segment and backslash', '/./\\evil.example'],
  ])('refuses a %s target', (_kind, from) => {
    expect(safeRedirectPath(from, ORIGIN)).toBe('/dashboard')
  })

  it('falls back without a target', () => {
    expect(safeRedirectPath(null, ORIGIN)).toBe('/dashboard')
    expect(safeRedirectPath('', ORIGIN)).toBe('/dashboard')
  })
})
