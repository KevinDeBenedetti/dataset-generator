import { describe, expect, it } from 'vitest'
import { differsFromCard, scheduleForm, skipNotice, toSchedule } from './schedule-state'

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

describe('a schedule compared with its card', () => {
  const saved = {
    options: { max_repos: null, full_refresh: false, sources: ['profile', 'repos'] },
    model_ref: 'openai:m',
  }

  it('matches when the card shows what the schedule runs', () => {
    expect(
      differsFromCard(saved, {
        // An empty number is left out by the card, null in the schedule.
        options: { full_refresh: false, sources: ['repos', 'profile'] },
        modelRef: 'openai:m',
      }),
    ).toBe(false)
  })

  it('differs on an option, a list or the model', () => {
    const card = {
      options: { full_refresh: false, sources: ['profile', 'repos'] },
      modelRef: 'openai:m',
    }
    expect(
      differsFromCard(saved, { ...card, options: { ...card.options, full_refresh: true } }),
    ).toBe(true)
    expect(differsFromCard(saved, { ...card, options: { ...card.options, max_repos: 2 } })).toBe(
      true,
    )
    expect(
      differsFromCard(saved, { ...card, options: { ...card.options, sources: ['profile'] } }),
    ).toBe(true)
    expect(differsFromCard(saved, { ...card, modelRef: null })).toBe(true)
  })
})

describe('a schedule whose latest time started no run', () => {
  it('says when and why, as a message that ends the reason itself', () => {
    const notice = skipNotice({
      reason: "Unknown model 'openai:x'. Available: openai:y.\n",
      at: '2026-11-17T18:00:00Z',
    })
    expect(notice).toEqual({
      key: 'schedule.skipped',
      at: '2026-11-17T18:00:00Z',
      // No final full stop: the message puts its own after the reason.
      reason: "Unknown model 'openai:x'. Available: openai:y",
    })
  })

  it('says nothing when the latest time ran, or was never due', () => {
    expect(skipNotice(null)).toBeNull()
    expect(skipNotice(undefined)).toBeNull()
    expect(skipNotice({ reason: '', at: '2026-11-17T18:00:00Z' })).toBeNull()
  })
})
