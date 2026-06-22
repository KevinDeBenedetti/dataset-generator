/**
 * Next.js instrumentation hook. Runs once when the server process boots.
 * When DEBUG_LOGS is enabled, patch console so the Next.js server logs are
 * captured for the dev log console (streamed via /api/debug/logs).
 */
export async function register() {
  const debug = (process.env.DEBUG_LOGS ?? '').toLowerCase()
  const enabled = debug !== '' && debug !== '0' && debug !== 'false' && debug !== 'no'

  if (enabled && process.env.NEXT_RUNTIME === 'nodejs') {
    const { patchConsole } = await import('./lib/dev-logs')
    patchConsole()
  }
}
