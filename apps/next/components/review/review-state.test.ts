import { describe, expect, it } from 'vitest'
import type { TabularDraft } from '../../api/sdk'
import { percent, reviewState, withStep } from './review-state'

function draft(overrides: Partial<TabularDraft>): TabularDraft {
  return {
    run_id: 'r',
    status: 'succeeded',
    kind: 'table',
    recipe_id: 'x',
    data_source_id: 's',
    target_repo: 'a/b',
    visibility: 'private',
    provenance: {},
    rows: 1,
    source_rows: 1,
    schema: [],
    profile: {},
    quality_report: {},
    blocking: [],
    step_rows: [],
    steps: [],
    changes: null,
    review: null,
    published_url: null,
    ...overrides,
  }
}

describe('reviewState', () => {
  it('allows both decisions on a clean succeeded draft', () => {
    expect(reviewState(draft({}))).toEqual({ canApprove: true, canReject: true, reasons: [] })
  })

  it('disables approve with the reasons while a rule blocks', () => {
    const state = reviewState(
      draft({ blocking: [{ rule: 'unmasked_pii', status: 'block', message: "'email' …" }] }),
    )
    expect(state.canApprove).toBe(false)
    expect(state.canReject).toBe(true)
    expect(state.reasons).toEqual(["'email' …"])
  })

  it('disables approve for a public draft whose licence does not allow it', () => {
    const state = reviewState(draft({ visibility: 'public', public_refusal: 'no licence' }))
    expect(state).toEqual({ canApprove: false, canReject: true, reasons: ['no licence'] })
    expect(
      reviewState(draft({ visibility: 'private', public_refusal: 'no licence' })).canApprove,
    ).toBe(true)
  })

  it('decides nothing once rejected or published', () => {
    expect(reviewState(draft({ status: 'rejected' })).canReject).toBe(false)
    expect(reviewState(draft({ status: 'published' })).canApprove).toBe(false)
    expect(reviewState(undefined).canApprove).toBe(false)
  })
})

describe('withStep', () => {
  it('adds a step once', () => {
    const mask = { op: 'mask', column: 'email', method: 'hash' }
    const once = withStep([], mask)
    expect(once).toEqual([mask])
    expect(withStep(once, { ...mask })).toEqual([mask])
  })
})

describe('percent', () => {
  it('formats a share', () => {
    expect(percent(0.1234, 'en')).toBe('12.3%')
    expect(percent(null, 'en')).toBe('—')
  })
})
