// Where a `?from=` deep link may send the user after login: only to a path on
// this very origin. The value is parsed the way the browser will resolve it,
// because a prefix check is not enough — `/\evil.com` or `/<tab>/evil.com`
// start with a single slash yet the URL parser turns them into `//evil.com`.
export function safeRedirectPath(
  from: string | null,
  origin: string,
  fallback = '/dashboard',
): string {
  if (!from || !from.startsWith('/')) return fallback
  let url: URL
  try {
    url = new URL(from, origin)
  } catch {
    return fallback
  }
  if (url.origin !== origin) return fallback
  return `${url.pathname}${url.search}${url.hash}`
}
