/**
 * Next.js instrumentation hook. Runs once when the server process boots.
 * When DEBUG_LOGS is enabled (in development only), patch console so the
 * Next.js server logs are captured for the dev log console (streamed via
 * /api/debug/logs).
 */
import { debugLogsEnabled } from './lib/debug-flag'

export async function register() {
  const enabled = debugLogsEnabled(process.env.DEBUG_LOGS, process.env.NODE_ENV)

  if (enabled && process.env.NEXT_RUNTIME === 'nodejs') {
    const { patchConsole } = await import('./lib/dev-logs')
    patchConsole()
  }
}
