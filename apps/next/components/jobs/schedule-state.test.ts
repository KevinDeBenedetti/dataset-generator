import { describe, expect, it } from 'vitest'
import { scheduleForm, toSchedule } from './schedule-state'

describe('a schedule picker', () => {
  it('starts off, at 03:00, publishing once switched on', () => {
    expect(scheduleForm(null)).toEqual({ every: '', time: '03:00', publish: true })
    expect(toSchedule(scheduleForm(null))).toBeNull()
  })

  it('shows a saved schedule and sends it back unchanged', () => {
    const saved = {
      every: 'week' as const,
      at_hour: 4,
      at_minute: 5,
      publish: false,
    }
    const form = scheduleForm(saved)
    expect(form).toEqual({ every: 'week', time: '04:05', publish: false })
    expect(toSchedule(form)).toEqual({ every: 'week', at_hour: 4, at_minute: 5, publish: false })
  })

  it('falls back to 03:00 for a time it cannot read', () => {
    expect(toSchedule({ every: 'day', time: '', publish: true })).toEqual({
      every: 'day',
      at_hour: 3,
      at_minute: 0,
      publish: true,
    })
    expect(toSchedule({ every: 'day', time: '25:99', publish: true })?.at_hour).toBe(3)
  })
})
