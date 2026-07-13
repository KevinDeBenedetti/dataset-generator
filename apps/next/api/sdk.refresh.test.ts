// Tests for the silent-session-refresh interceptor registered in `sdk.ts`
// (`client.interceptors.response.use(...)`). Drives it through the real
// `@hey-api/client-fetch` request pipeline with a mocked `fetch`, rather than
// unit-testing the interceptor function in isolation (it isn't exported).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function pathnameOf(input: RequestInfo | URL): string {
  const url =
    typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
  return new URL(url).pathname
}

// `sdk.ts` imports `client` from `./client.gen` and mutates it (setConfig +
// the refresh interceptor) but doesn't re-export it, so tests need both: the
// singleton itself, and `sdk.ts` evaluated for its side effects. Importing
// `./client.gen` first guarantees the same module instance `sdk.ts` mutates
// (both resolve from the same cache within one `vi.resetModules()` epoch).
async function loadClient() {
  const { client } = await import('./client.gen')
  await import('./sdk')
  return client
}

describe('sdk.ts silent session refresh', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    // Fresh module state per test — `refreshInFlight` is module-level, so a
    // stale value from a previous test would leak across cases.
    vi.resetModules()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('replays the original request after a successful refresh', async () => {
    let datasetCalls = 0
    let refreshCalls = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const path = pathnameOf(input)
      if (path === '/auth/refresh') {
        refreshCalls++
        return new Response(null, { status: 200 })
      }
      if (path === '/dataset') {
        datasetCalls++
        return datasetCalls === 1
          ? new Response(null, { status: 401 })
          : jsonResponse(200, [{ id: '1', name: 'ds' }])
      }
      throw new Error(`unexpected fetch: ${path}`)
    })

    const client = await loadClient()
    const result = await client.get({ url: '/dataset' })

    expect(refreshCalls).toBe(1)
    expect(datasetCalls).toBe(2) // original 401 + replayed 200
    expect(result.response.status).toBe(200)
    expect(result.data).toEqual([{ id: '1', name: 'ds' }])
  })

  it('dedupes concurrent 401s into a single refresh call', async () => {
    let refreshCalls = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const path = pathnameOf(input)
      if (path === '/auth/refresh') {
        refreshCalls++
        // Resolve on a later microtask so both concurrent 401s are already
        // "in flight" and waiting on the same refresh promise.
        await Promise.resolve()
        return new Response(null, { status: 200 })
      }
      if (path === '/dataset') {
        // Every attempt (initial or replayed) comes back 401 — irrelevant to
        // this test, which only cares how many times /auth/refresh fired.
        return new Response(null, { status: 401 })
      }
      throw new Error(`unexpected fetch: ${path}`)
    })

    const client = await loadClient()
    await Promise.all([client.get({ url: '/dataset' }), client.get({ url: '/dataset' })])

    expect(refreshCalls).toBe(1)
  })

  it('does not attempt a refresh for NO_REFRESH_PATHS (e.g. /auth/login)', async () => {
    let refreshCalls = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const path = pathnameOf(input)
      if (path === '/auth/refresh') {
        refreshCalls++
        return new Response(null, { status: 200 })
      }
      if (path === '/auth/login') {
        return jsonResponse(401, { detail: 'Invalid credentials' })
      }
      throw new Error(`unexpected fetch: ${path}`)
    })

    const client = await loadClient()
    const result = await client.get({ url: '/auth/login' })

    expect(refreshCalls).toBe(0)
    expect(result.response.status).toBe(401)
  })

  it('returns the original 401 unchanged when the refresh itself fails', async () => {
    let datasetCalls = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const path = pathnameOf(input)
      if (path === '/auth/refresh') {
        return new Response(null, { status: 401 })
      }
      if (path === '/dataset') {
        datasetCalls++
        return new Response(null, { status: 401 })
      }
      throw new Error(`unexpected fetch: ${path}`)
    })

    const client = await loadClient()
    const result = await client.get({ url: '/dataset' })

    expect(datasetCalls).toBe(1) // no retry — the refresh didn't succeed
    expect(result.response.status).toBe(401)
  })
})
