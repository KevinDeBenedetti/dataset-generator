// `.env.example` ships NEXT_PUBLIC_* keys with no value and compose forwards
// them as "", which `??` does not replace — so each default must survive "".
import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('blank NEXT_PUBLIC_* values fall back to the defaults', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('proxy still recognises the default refresh cookie', async () => {
    vi.stubEnv('NEXT_PUBLIC_AUTH_COOKIE_NAME', '')
    vi.stubEnv('NEXT_PUBLIC_REFRESH_COOKIE_NAME', '')
    const { proxy } = await import('./proxy')

    // Access cookie already expired: only the refresh cookie is left.
    const request = new NextRequest('http://localhost:3000/dashboard', {
      headers: { cookie: 'refresh_token=abc' },
    })
    const response = proxy(request)

    expect(response.headers.get('location')).toBeNull()
  })

  it('oidcLoginUrl stays absolute', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', '')
    const { oidcLoginUrl } = await import('./api/sdk')

    expect(oidcLoginUrl()).toBe('http://localhost:8000/auth/oidc/login')
  })
})
