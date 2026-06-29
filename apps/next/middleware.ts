import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// Name of the httpOnly auth cookie set by the API (see AUTH_COOKIE_NAME).
const AUTH_COOKIE = process.env.NEXT_PUBLIC_AUTH_COOKIE_NAME ?? 'access_token'

// Routes reachable without authentication. Everything else (the whole `(app)`
// shell: /dashboard, /datasets, /generate, /jobs, /quality, /sources, …) is
// gated — new app routes are protected automatically, no per-route allowlist
// to maintain.
const PUBLIC_PATHS = ['/', '/login']

// Middleware-level gate: presence of the auth cookie. The cookie is httpOnly
// and set by the API on host `localhost` (shared across ports in dev), so the
// middleware can read it. It only checks presence — the JWT is verified by the
// API on each request (and by /auth/me). If the front and API ever live on
// different domains, the cookie won't be visible here and this must move to a
// same-origin proxy or a server-readable token.
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const isAuthenticated = Boolean(request.cookies.get(AUTH_COOKIE)?.value)
  const isPublic = PUBLIC_PATHS.includes(pathname)

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

  return NextResponse.next()
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
