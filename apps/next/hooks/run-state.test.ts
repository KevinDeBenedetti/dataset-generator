import { describe, expect, it } from 'vitest'
import { runEnded } from './run-state'

describe('runEnded', () => {
  it('is true when a run watched while active has just finished', () => {
    expect(runEnded('running', 'succeeded')).toBe(true)
    expect(runEnded('queued', 'failed')).toBe(true)
    expect(runEnded('publishing', 'succeeded')).toBe(true)
    expect(runEnded('running', 'cancelled')).toBe(true)
  })

  it('is false while it runs, and for a run first seen finished', () => {
    expect(runEnded('queued', 'running')).toBe(false)
    expect(runEnded('running', 'running')).toBe(false)
    expect(runEnded(undefined, 'succeeded')).toBe(false) // opened after the end
    expect(runEnded('succeeded', 'succeeded')).toBe(false)
  })
})
