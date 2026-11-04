import { describe, expect, it } from 'vitest'
import { applyPatch, parseHubState, serializeHubState } from './url-state'

describe('hub URL state', () => {
  it('defaults to the first page of the data tab', () => {
    const state = parseHubState(new URLSearchParams())
    expect(state).toMatchObject({ tab: 'data', page: 1, size: 25, filters: [], row: null })
    expect(serializeHubState(state)).toBe('')
  })

  it('round-trips a full view', () => {
    const query =
      'tab=stats&rev=abc&split=review&q=alpha&page=3&size=50&sort=confidence&order=desc' +
      '&f=%5B%7B%22column%22%3A%22category%22%2C%22op%22%3A%22eq%22%2C%22value%22%3A%22docs%22%7D%5D' +
      '&layout=table&row=7'
    const state = parseHubState(new URLSearchParams(query))

    expect(state).toMatchObject({
      tab: 'stats',
      rev: 'abc',
      split: 'review',
      q: 'alpha',
      page: 3,
      size: 50,
      sort: 'confidence',
      order: 'desc',
      filters: [{ column: 'category', op: 'eq', value: 'docs' }],
      layout: 'table',
      row: 7,
    })
    expect(parseHubState(new URLSearchParams(serializeHubState(state)))).toEqual(state)
  })

  it('ignores values it does not know', () => {
    const state = parseHubState(
      new URLSearchParams(
        'tab=nope&size=7&page=-2&f=%5B%7B%22op%22%3A%22drop%22%7D%5D&layout=grid',
      ),
    )
    expect(state).toMatchObject({ tab: 'data', size: 25, page: 1, filters: [], layout: null })
  })

  it('goes back to the first page when the rows change', () => {
    const state = parseHubState(new URLSearchParams('page=4'))
    expect(applyPatch(state, { q: 'beta' }).page).toBe(1)
    expect(applyPatch(state, { row: 3 }).page).toBe(4)
    expect(applyPatch(state, { page: 2, q: 'x' }).page).toBe(2)
  })
})
