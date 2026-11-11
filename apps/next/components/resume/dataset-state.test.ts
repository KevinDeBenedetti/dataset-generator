import { describe, expect, it } from 'vitest'
import type { ResumeDatasetOut } from '../../api/types'
import { initialForm, isDirty, toSettings } from './dataset-state'

const RESUME = { name: 'Engineer', slug: 'engineer' }

const SAVED: ResumeDatasetOut = {
  resume_id: 'r1',
  title: 'Engineer',
  target_repo: 'kevin/resume-engineer',
  language: 'fr',
  model_ref: 'openai:chat-default',
  every: 'week',
  at_hour: 6,
  at_minute: 30,
  publish: false,
  next_run_at: null,
  latest_run: null,
  updated_at: '2026-11-10T10:00:00Z',
}

describe('the resume dataset form', () => {
  it('starts from a dataset named after the resume, in your namespace, unscheduled', () => {
    expect(initialForm(RESUME, null, 'kevin')).toEqual({
      target_repo: 'kevin/resume-engineer',
      language: 'auto',
      model_ref: null,
      every: '',
      time: '03:00',
      publish: true,
    })
    expect(initialForm({ name: 'My CV', slug: '' }, null, null).target_repo).toBe('resume-my-cv')
  })

  it('shows the saved settings and sends them back unchanged', () => {
    const form = initialForm(RESUME, SAVED, 'kevin')
    expect(form.time).toBe('06:30')
    expect(toSettings(form)).toEqual({
      target_repo: 'kevin/resume-engineer',
      language: 'fr',
      model_ref: 'openai:chat-default',
      every: 'week',
      at_hour: 6,
      at_minute: 30,
      publish: false,
    })
    expect(isDirty(form, RESUME, SAVED, 'kevin')).toBe(false)
  })

  it('sends no schedule and your LLM for empty choices, the time as numbers', () => {
    const settings = toSettings({
      ...initialForm(RESUME, null, 'kevin'),
      target_repo: '  kevin/cv  ',
      time: '21:05',
    })
    expect(settings).toMatchObject({
      target_repo: 'kevin/cv',
      every: null,
      model_ref: null,
      at_hour: 21,
      at_minute: 5,
    })
  })

  it('is dirty before a first save, and after any change', () => {
    expect(isDirty(initialForm(RESUME, null, 'kevin'), RESUME, null, 'kevin')).toBe(true)
    const changed = { ...initialForm(RESUME, SAVED, 'kevin'), every: 'day' as const }
    expect(isDirty(changed, RESUME, SAVED, 'kevin')).toBe(true)
  })
})
