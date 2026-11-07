import { describe, expect, it } from 'vitest'
import { debugLogsEnabled } from './debug-flag'

describe('debugLogsEnabled', () => {
  it('is on with the flag set, in development', () => {
    for (const flag of ['1', 'true', 'yes', 'on']) {
      expect(debugLogsEnabled(flag, 'development')).toBe(true)
    }
  })

  it('is off without the flag, or with it turned off', () => {
    for (const flag of [undefined, '', '0', 'false', 'FALSE', 'no']) {
      expect(debugLogsEnabled(flag, 'development')).toBe(false)
    }
  })

  it('never streams the logs outside development, whatever the flag says', () => {
    expect(debugLogsEnabled('1', 'production')).toBe(false)
    expect(debugLogsEnabled('1', 'test')).toBe(false)
    expect(debugLogsEnabled('1', undefined)).toBe(false)
  })
})
