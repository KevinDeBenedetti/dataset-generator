import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const IS_PROD = process.env.NODE_ENV === 'production'

// Names of the httpOnly auth cookies set by the API (see AUTH_COOKIE_NAME and
// AUTH_REFRESH_COOKIE_NAME). Read at *runtime* on the server (not inlined at
// build like NEXT_PUBLIC_*), so one image serves any environment. The defaults
// mirror the API's: outside development the cookies carry the `__Host-` prefix.
const AUTH_COOKIE =
  process.env.AUTH_COOKIE_NAME || (IS_PROD ? '__Host-access_token' : 'access_token')
const REFRESH_COOKIE =
  process.env.AUTH_REFRESH_COOKIE_NAME || (IS_PROD ? '__Host-refresh_token' : 'refresh_token')

// Origin of an absolute API base URL, if one is configured (in the default
// single-host production topology the API is same-origin under /api).
function apiOrigin(): string {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_BASE_URL ?? '').origin
  } catch {
    return ''
  }
}

// Per-request Content-Security-Policy with a nonce (Next applies the nonce to
// its own scripts when it finds it in the request's CSP header). Production
// only: development needs eval and websockets for hot reload.
function contentSecurityPolicy(nonce: string): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    // React writes inline style attributes; styles can't run code.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    `connect-src 'self' ${apiOrigin()}`.trim(),
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; ')
}

// Routes reachable without authentication. Everything else (the whole `(app)`
// shell: /dashboard, /datasets, /generate, /jobs, /quality, /sources, …) is
// gated — new app routes are protected automatically, no per-route allowlist
// to maintain.
const PUBLIC_PATHS = new Set(['/', '/login'])

// Proxy-level gate: presence of the auth cookie. The cookie is httpOnly and set
// by the API on host `localhost` (shared across ports in dev), so the proxy can
// read it. It only checks presence — the JWT is verified by the API on each
// request (and by /auth/me). If the front and API ever live on different
// domains, the cookie won't be visible here and this must move to a same-origin
// proxy or a server-readable token.
//
// `proxy.ts` is the Next 16 replacement for `middleware.ts`; it runs on the
// nodejs runtime (edge is not supported), which this cookie check doesn't need.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  // The access cookie expires quickly (short max_age); the refresh cookie is
  // what marks a still-renewable session — the API client refreshes the access
  // token transparently on the first 401. Either one counts as signed in.
  const isAuthenticated = Boolean(
    request.cookies.get(AUTH_COOKIE)?.value || request.cookies.get(REFRESH_COOKIE)?.value,
  )
  const isPublic = PUBLIC_PATHS.has(pathname)

  // Already signed in but heading to /login → send to the app.
  if (pathname === '/login' && isAuthenticated) {
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }

  // Protected route without a session → bounce to /login (remember where).
  if (!isPublic && !isAuthenticated) {
    const loginUrl = new URL('/login', request.url)
    loginUrl.searchParams.set('from', pathname)
    return NextResponse.redirect(loginUrl)
  }

  if (!IS_PROD) return NextResponse.next()

  // Generic base64 nonce, new for every request.
  const nonce = btoa(crypto.randomUUID())
  const csp = contentSecurityPolicy(nonce)
  const requestHeaders = new Headers(request.headers)
  requestHeaders.set('x-nonce', nonce)
  requestHeaders.set('Content-Security-Policy', csp)
  const response = NextResponse.next({ request: { headers: requestHeaders } })
  response.headers.set('Content-Security-Policy', csp)
  return response
}

// Run on everything except Next internals, the API-proxy route and static
// assets. The trailing extension group excludes files served from `public/`
// (file.svg, globe.svg, …) so unauthenticated asset requests are served
// instead of being redirected to /login.
export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|api/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|avif|ico|bmp|woff|woff2|ttf|otf|eot|txt|xml|json|webmanifest|map)$).*)',
  ],
}
