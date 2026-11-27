import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

// The sign-in gate: which requests reach a page, which go to /login and back.
// IS_PROD and the cookie names are read when the module loads, so each test
// imports it afresh under the NODE_ENV it needs.
async function gate(env: 'development' | 'production' = 'development') {
  vi.stubEnv('NODE_ENV', env)
  vi.resetModules()
  return import('./proxy')
}

function request(path: string, cookie = '') {
  return new NextRequest(`http://localhost:3020${path}`, {
    headers: cookie ? { cookie } : {},
  })
}

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('proxy', () => {
  it('lets the homepage and the sign-in page through without a session', async () => {
    const { proxy } = await gate()
    expect(proxy(request('/')).headers.get('location')).toBeNull()
    expect(proxy(request('/login')).headers.get('location')).toBeNull()
  })

  it("lets the admin's sign-in page through without a session", async () => {
    const { proxy } = await gate()
    expect(proxy(request('/admin/login')).headers.get('location')).toBeNull()
    // The rest of /admin stays behind the gate.
    expect(proxy(request('/admin')).headers.get('location')).toBe(
      'http://localhost:3020/login?from=%2Fadmin',
    )
  })

  it('sends a protected page to /login, remembering where', async () => {
    const { proxy } = await gate()
    const location = proxy(request('/datasets')).headers.get('location')
    expect(location).toBe('http://localhost:3020/login?from=%2Fdatasets')
  })

  it('takes either cookie as a session for a protected page', async () => {
    const { proxy } = await gate()
    expect(proxy(request('/dashboard', 'access_token=a')).headers.get('location')).toBeNull()
    expect(proxy(request('/dashboard', 'refresh_token=r')).headers.get('location')).toBeNull()
  })

  it('sends a signed-in user away from /login, but only with a live access cookie', async () => {
    const { proxy } = await gate()
    expect(proxy(request('/login', 'access_token=a')).headers.get('location')).toBe(
      'http://localhost:3020/dashboard',
    )
    // A refresh cookie alone may be one the API refuses: /login stays reachable.
    expect(proxy(request('/login', 'refresh_token=r')).headers.get('location')).toBeNull()
  })

  it('reads the __Host- cookies in production and sets a nonce CSP', async () => {
    const { proxy } = await gate('production')
    expect(proxy(request('/dashboard', 'access_token=a')).headers.get('location')).toContain(
      '/login',
    )
    const response = proxy(request('/dashboard', '__Host-access_token=a'))
    const csp = response.headers.get('content-security-policy') ?? ''
    expect(csp).toMatch(/script-src 'self' 'nonce-[^']+' 'strict-dynamic'/)
    expect(csp).toContain("frame-ancestors 'none'")
  })

  it('leaves static assets and the API proxy route out of the matcher', async () => {
    const { config } = await gate()
    const matcher = new RegExp(`^${config.matcher[0]}$`)
    for (const path of ['/dashboard', '/datasets/kevin/x', '/login']) {
      expect(matcher.test(path), path).toBe(true)
    }
    for (const path of ['/_next/static/chunks/a.js', '/api/health', '/logo.svg', '/favicon.ico']) {
      expect(matcher.test(path), path).toBe(false)
    }
  })
})
