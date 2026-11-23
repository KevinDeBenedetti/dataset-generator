// ── Silent session refresh ───────────────────────────────────────────────────
// The access token is a short-lived httpOnly cookie; a long-lived refresh
// cookie (rotated server-side on every use) can renew it. When an API call
// comes back 401, try POST /auth/refresh once and replay the request, so an
// expired access token never surfaces as a logout mid-session. The generated
// client does it in an interceptor (sdk.ts); a raw request, such as the file
// upload, goes through fetchWithRefresh.

// A 401 from these endpoints is a definitive answer — refreshing would either
// loop (/auth/refresh) or mask a real credential failure.
const NO_REFRESH_PATHS = ['/auth/login', '/auth/logout', '/auth/refresh', '/auth/providers']

export function needsNoRefresh(url: string): boolean {
  const path = new URL(url).pathname
  return NO_REFRESH_PATHS.some((p) => path.endsWith(p))
}

let refreshInFlight: Promise<boolean> | null = null

// Concurrent 401s (e.g. several queries firing on a page load) share a single
// refresh attempt — rotation makes the refresh cookie single-use, so parallel
// calls would revoke each other's tokens.
export function tryRefreshSession(baseUrl: string): Promise<boolean> {
  refreshInFlight ??= fetch(`${baseUrl}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshInFlight = null
    })
  return refreshInFlight
}

/** `fetch` with the session's cookies, renewing an expired session once and
 *  sending the request again. The body is reused as is: a FormData or a
 *  string, not a stream. */
export async function fetchWithRefresh(url: string, init: RequestInit = {}): Promise<Response> {
  const request = { ...init, credentials: 'include' as const }
  const response = await fetch(url, request)
  if (response.status !== 401 || needsNoRefresh(url)) return response
  if (!(await tryRefreshSession(new URL(url).origin))) return response
  return fetch(url, request)
}
