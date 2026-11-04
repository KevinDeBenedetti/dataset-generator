import { describe, expect, it } from 'vitest'
import {
  compactJson,
  datasetHref,
  formatBytes,
  formatCount,
  formatPercent,
  formatValue,
  isHttpUrl,
  shortSha,
  splitRepoId,
  timeAgo,
} from './format'

describe('formatBytes', () => {
  it.each([
    [null, '—'],
    [0, '0 B'],
    [1023, '1023 B'],
    [1536, '1.5 KB'],
    [230 * 1024 * 1024, '230 MB'],
  ])('%s → %s', (value, expected) => {
    expect(formatBytes(value)).toBe(expected)
  })
})

describe('formatCount', () => {
  it('writes counts in full under 10,000 and compact above', () => {
    expect(formatCount(1284)).toBe('1,284')
    expect(formatCount(12_900)).toBe('12.9K')
    expect(formatCount(4_200_000)).toBe('4.2M')
    expect(formatCount(undefined)).toBe('—')
  })
})

describe('formatValue', () => {
  it('keeps whole numbers whole and rounds the rest', () => {
    expect(formatValue(42)).toBe('42')
    expect(formatValue(0.87654)).toBe('0.877')
  })
})

describe('formatPercent', () => {
  it('rounds, flags tiny shares and survives an empty whole', () => {
    expect(formatPercent(1, 3)).toBe('33%')
    expect(formatPercent(1, 500)).toBe('<1%')
    expect(formatPercent(0, 10)).toBe('0%')
    expect(formatPercent(3, 0)).toBe('0%')
  })
})

describe('timeAgo', () => {
  const now = Date.parse('2026-11-04T12:00:00Z')

  it.each([
    ['2026-11-04T11:59:40Z', 'just now'],
    ['2026-11-04T11:55:00Z', '5m ago'],
    ['2026-11-04T09:00:00Z', '3h ago'],
    ['2026-11-02T12:00:00Z', '2d ago'],
    ['2026-10-14T12:00:00Z', '3w ago'],
    ['2026-06-04T12:00:00Z', '5mo ago'],
    ['2024-11-04T12:00:00Z', '2y ago'],
    ['not a date', '—'],
  ])('%s → %s', (value, expected) => {
    expect(timeAgo(value, now)).toBe(expected)
  })
})

describe('repo ids', () => {
  it('splits on the first slash only', () => {
    expect(splitRepoId('kevin/qa')).toEqual({ owner: 'kevin', name: 'qa' })
    expect(splitRepoId('qa')).toEqual({ owner: '', name: 'qa' })
  })

  it('builds the app page of a dataset', () => {
    expect(datasetHref('kevin/github-qa')).toBe('/datasets/kevin/github-qa')
    expect(datasetHref('my org/a b')).toBe('/datasets/my%20org/a%20b')
  })
})

describe('cells', () => {
  it('recognizes web links only', () => {
    expect(isHttpUrl('https://github.com/kevin')).toBe(true)
    expect(isHttpUrl('javascript:alert(1)')).toBe(false)
    expect(isHttpUrl('github://kevin')).toBe(false)
  })

  it('prints nested values on one line', () => {
    expect(compactJson({ a: [1, 2] })).toBe('{"a":[1,2]}')
    expect(shortSha('0123456789abcdef')).toBe('0123456')
  })
})
