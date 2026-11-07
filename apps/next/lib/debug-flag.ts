/**
 * Whether the dev log console is on: `DEBUG_LOGS` (or its browser twin
 * `NEXT_PUBLIC_DEBUG_LOGS`) set to anything but off, in development only.
 *
 * The console streams the raw server logs without authentication, so like the
 * API's `/debug/logs` it never exists in a production build, whatever the flag
 * says. Pure, so the three places that gate on it share one reading of the
 * flag: `instrumentation.ts`, `app/api/debug/logs/route.ts` and the console.
 */
export function debugLogsEnabled(flag: string | undefined, nodeEnv: string | undefined): boolean {
  const value = (flag ?? '').toLowerCase()
  const on = value !== '' && value !== '0' && value !== 'false' && value !== 'no'
  return on && nodeEnv === 'development'
}
