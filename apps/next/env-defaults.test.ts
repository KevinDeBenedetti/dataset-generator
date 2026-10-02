// `.env.example` ships keys with no value and compose forwards them as "",
// which `??` does not replace — so each default must survive "".
import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => {
  vi.resetModules()
})

afterEach(() => {
  vi.unstubAllEnvs()
})

function request(cookie?: string, path = '/dashboard') {
  return new NextRequest(`http://localhost:3000${path}`, {
    headers: cookie ? { cookie } : {},
  })
}

describe('blank values fall back to the defaults', () => {
  it('proxy still recognises the default refresh cookie', async () => {
    const { proxy } = await import('./proxy')

    // Access cookie already expired: only the refresh cookie is left.
    const response = proxy(request('refresh_token=abc'))

    expect(response.headers.get('location')).toBeNull()
  })

  it('ssoUrl stays absolute in development', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', '')
    const { ssoUrl } = await import('./api/sdk')

    expect(ssoUrl('github')).toBe('http://localhost:8000/auth/github/login')
    expect(ssoUrl('infomaniak', 'link')).toBe('http://localhost:8000/auth/infomaniak/link')
  })
})

describe('production', () => {
  beforeEach(() => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', '')
  })

  it('calls the API on the same origin under /api', async () => {
    const { ssoUrl } = await import('./api/sdk')

    expect(ssoUrl('github')).toBe('/api/auth/github/login')
  })

  it('reads the __Host- prefixed session cookies the API sets', async () => {
    const { proxy } = await import('./proxy')

    expect(proxy(request('__Host-refresh_token=abc')).headers.get('location')).toBeNull()
    expect(proxy(request('__Host-access_token=abc')).headers.get('location')).toBeNull()
    // The unprefixed dev names no longer count as a session.
    const denied = proxy(request('refresh_token=abc'))
    expect(denied.headers.get('location')).toContain('/login?from=%2Fdashboard')
  })

  it('sends a per-request CSP whose nonce is also handed to the app', async () => {
    const { proxy } = await import('./proxy')

    const first = proxy(request('__Host-refresh_token=abc'))
    const second = proxy(request('__Host-refresh_token=abc'))
    const csp = first.headers.get('content-security-policy') ?? ''
    const nonce = /'nonce-([^']+)'/.exec(csp)?.[1]

    expect(nonce).toBeTruthy()
    expect(nonce).not.toBe(
      /'nonce-([^']+)'/.exec(second.headers.get('content-security-policy') ?? '')?.[1],
    )
    expect(csp).toContain("default-src 'self'")
    expect(csp).toContain("frame-ancestors 'none'")
    expect(csp).toContain("object-src 'none'")
    expect(csp).not.toContain('unsafe-eval')
    // Next reads the nonce from the *request* headers it forwards.
    expect(first.headers.get('x-middleware-request-x-nonce')).toBe(nonce)
  })

  it('lets an absolute API origin through connect-src', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.example.com/v1')
    const { proxy } = await import('./proxy')

    const csp = proxy(request('__Host-refresh_token=abc')).headers.get('content-security-policy')
    expect(csp).toContain("connect-src 'self' https://api.example.com")
  })

  it('does not set a CSP on redirects to /login', async () => {
    const { proxy } = await import('./proxy')

    expect(proxy(request()).headers.get('content-security-policy')).toBeNull()
  })
})

describe('development', () => {
  it('sets no CSP (hot reload needs eval and websockets)', async () => {
    const { proxy } = await import('./proxy')

    const response = proxy(request('refresh_token=abc'))
    expect(response.headers.get('content-security-policy')).toBeNull()
  })
})
