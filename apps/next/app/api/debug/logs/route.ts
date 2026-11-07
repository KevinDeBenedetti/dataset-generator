import type { NextRequest } from 'next/server'
import { debugLogsEnabled } from '@/lib/debug-flag'
import { snapshot, subscribe } from '@/lib/dev-logs'

/**
 * Dev log console SSE endpoint. Merges two sources into one same-origin stream:
 *
 *  - Next.js server logs, captured in-process (see `lib/dev-logs.ts`)
 *  - FastAPI server logs, proxied from the backend's own `/debug/logs` SSE
 *
 * Each event is a JSON object `{ source: 'next' | 'fastapi', line: string }`.
 * Returns 404 unless DEBUG_LOGS is enabled, and always outside development:
 * the stream has no authentication.
 */

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const DEBUG_ENABLED = debugLogsEnabled(process.env.DEBUG_LOGS, process.env.NODE_ENV)

// Server-to-server URL for the FastAPI container (compose service name), which
// differs from the browser-facing NEXT_PUBLIC_API_BASE_URL (localhost).
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? 'http://server:8000'

type LogEvent = { source: 'next' | 'fastapi'; line: string }

export async function GET(req: NextRequest): Promise<Response> {
  if (!DEBUG_ENABLED) {
    return new Response('Not found', { status: 404 })
  }

  const encoder = new TextEncoder()

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let closed = false
      const send = (event: LogEvent) => {
        if (closed) return
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
        } catch {
          closed = true
        }
      }

      // Replay the Next.js backlog, then stream new lines as they arrive.
      for (const line of snapshot()) send({ source: 'next', line })
      const unsubscribe = subscribe((line) => send({ source: 'next', line }))

      // Proxy the FastAPI SSE stream.
      const upstream = new AbortController()
      void pumpUpstream(upstream.signal, send)

      const cleanup = () => {
        if (closed) return
        closed = true
        unsubscribe()
        upstream.abort()
        try {
          controller.close()
        } catch {
          // already closed
        }
      }
      req.signal.addEventListener('abort', cleanup)
    },
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    },
  })
}

async function pumpUpstream(signal: AbortSignal, send: (event: LogEvent) => void): Promise<void> {
  try {
    const res = await fetch(`${API_INTERNAL_URL}/debug/logs`, {
      signal,
      headers: { Accept: 'text/event-stream' },
    })
    if (!res.body) return

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      // oxlint-disable-next-line no-await-in-loop -- a stream is read chunk by chunk
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() ?? ''
      for (const chunk of chunks) {
        const dataLine = chunk.split('\n').find((l) => l.startsWith('data:'))
        if (!dataLine) continue // keep-alive comment
        const payload = dataLine.slice('data:'.length).trim()
        try {
          send(JSON.parse(payload) as LogEvent)
        } catch {
          send({ source: 'fastapi', line: payload })
        }
      }
    }
  } catch {
    // Upstream unavailable or aborted — the Next.js logs still stream.
  }
}
