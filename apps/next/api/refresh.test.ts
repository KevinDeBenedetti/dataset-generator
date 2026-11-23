import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchWithRefresh, needsNoRefresh } from './refresh'

const API = 'http://localhost:8020'

function answers(...statuses: number[]) {
  const calls: { url: string; init?: RequestInit }[] = []
  const queue = [...statuses]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      return new Response('{}', { status: queue.shift() ?? 200 })
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchWithRefresh', () => {
  it('renews an expired session once and sends the request again, body included', async () => {
    const calls = answers(401, 200, 200) // the upload, the refresh, the replay
    const form = new FormData()
    form.append('dataset_name', 'docs')

    const response = await fetchWithRefresh(`${API}/dataset/generate/file`, {
      method: 'POST',
      body: form,
    })

    expect(response.status).toBe(200)
    expect(calls.map((c) => c.url)).toEqual([
      `${API}/dataset/generate/file`,
      `${API}/auth/refresh`,
      `${API}/dataset/generate/file`,
    ])
    expect(calls[2].init?.body).toBe(form)
    expect(calls.every((c) => c.init?.credentials === 'include')).toBe(true)
  })

  it('gives back the 401 when the session cannot be renewed', async () => {
    const calls = answers(401, 401)
    const response = await fetchWithRefresh(`${API}/me/export`)
    expect(response.status).toBe(401)
    expect(calls).toHaveLength(2) // no replay
  })

  it('never refreshes for the sign-in endpoints themselves', async () => {
    const calls = answers(401)
    const response = await fetchWithRefresh(`${API}/auth/login`, { method: 'POST' })
    expect(response.status).toBe(401)
    expect(calls).toHaveLength(1)
    expect(needsNoRefresh(`${API}/auth/refresh`)).toBe(true)
  })
})
