/**
 * Server-side capture of the Next.js process logs for the dev log console.
 *
 * `patchConsole()` (wired up from `instrumentation.ts` when DEBUG_LOGS is set)
 * wraps `console.*` so every line is also pushed into a bounded in-memory ring
 * buffer. The `/api/debug/logs` SSE route replays the buffer and subscribes for
 * new lines, merging them with the proxied FastAPI stream.
 *
 * Node.js-only module — never import it from a client component.
 */

type Listener = (line: string) => void

const CAPACITY = 500
const buffer: string[] = []
const listeners = new Set<Listener>()
let patched = false

export function recordLog(line: string): void {
  buffer.push(line)
  if (buffer.length > CAPACITY) buffer.shift()
  for (const listener of listeners) {
    try {
      listener(line)
    } catch {
      // A failing subscriber must never break logging.
    }
  }
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function snapshot(): string[] {
  return [...buffer]
}

function stringify(arg: unknown): string {
  if (typeof arg === 'string') return arg
  if (arg instanceof Error) return arg.stack ?? `${arg.name}: ${arg.message}`
  try {
    return JSON.stringify(arg)
  } catch {
    return String(arg)
  }
}

/** Wrap console.* so each call is mirrored into the ring buffer. Idempotent. */
export function patchConsole(): void {
  if (patched) return
  patched = true

  const levels = ['log', 'info', 'warn', 'error', 'debug'] as const
  for (const level of levels) {
    const original = console[level].bind(console)
    console[level] = (...args: unknown[]) => {
      original(...args)
      try {
        recordLog(`${level.toUpperCase()} | ${args.map(stringify).join(' ')}`)
      } catch {
        // Never let log capture throw.
      }
    }
  }
}
