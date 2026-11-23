import { describe, expect, it } from 'vitest'
import { ApiError, apiError, errorStatus, getErrorMessage, retryTransient } from './errors'

function failed(status: number, error: unknown) {
  return { error, response: new Response(null, { status }) }
}

describe('apiError', () => {
  it('keeps the status and the server detail', () => {
    const error = apiError(failed(404, { detail: "Unknown run 'x'" }), 'Failed')
    expect(error).toBeInstanceOf(ApiError)
    expect(errorStatus(error)).toBe(404)
    expect(error.message).toBe("Unknown run 'x'")
  })

  it('flattens a validation list and falls back without a detail', () => {
    const list = { detail: [{ loc: ['body', 'name'], msg: 'Field required' }] }
    expect(getErrorMessage(list, 'Failed')).toBe('name: Field required')
    expect(apiError(failed(500, null), 'Failed to save').message).toBe('Failed to save')
  })

  it('has no status for a network failure', () => {
    expect(errorStatus(apiError({ error: new TypeError('fetch failed') }, 'Failed'))).toBe(
      undefined,
    )
  })
})

const error = (status?: number) => new ApiError('x', status)

describe('retryTransient', () => {
  it('never retries a definitive answer', () => {
    for (const status of [400, 401, 403, 404, 409, 413, 422, 429]) {
      expect(retryTransient(0, error(status)), String(status)).toBe(false)
    }
  })

  it('retries a server or network failure twice', () => {
    for (const status of [500, 502, 503, 504, 408, undefined]) {
      expect(retryTransient(0, error(status)), String(status)).toBe(true)
      expect(retryTransient(1, error(status))).toBe(true)
      expect(retryTransient(2, error(status))).toBe(false)
    }
    expect(retryTransient(0, new Error('plain'))).toBe(true)
  })
})
