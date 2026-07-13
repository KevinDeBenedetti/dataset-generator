'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Terminal, X, Trash2, Pause, Play } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Floating dev log console. Streams merged FastAPI + Next.js server logs from
 * `/api/debug/logs` (SSE) into an in-browser terminal.
 *
 * Rendered only when NEXT_PUBLIC_DEBUG_LOGS is set (wired from DEBUG_LOGS in
 * docker-compose). Toggle with Ctrl+` (like the VS Code terminal) or the
 * floating button.
 */

const debugFlag = (process.env.NEXT_PUBLIC_DEBUG_LOGS ?? '').toLowerCase()
const ENABLED = debugFlag !== '' && debugFlag !== '0' && debugFlag !== 'false' && debugFlag !== 'no'

const MAX_LINES = 1000

type LogEntry = { id: number; source: 'next' | 'fastapi'; line: string }

function levelClass(line: string): string {
  if (/\bERROR\b|\bCRITICAL\b/.test(line)) return 'text-red-400'
  if (/\bWARN(ING)?\b/.test(line)) return 'text-amber-400'
  if (/\bDEBUG\b/.test(line)) return 'text-zinc-500'
  return 'text-zinc-300'
}

export function DevLogConsole() {
  const [open, setOpen] = useState(false)
  const [paused, setPaused] = useState(false)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const pausedRef = useRef(paused)
  const idRef = useRef(0)

  // Keep a ref in sync so the SSE handler reads the latest pause state without
  // resubscribing on every toggle.
  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  // Ctrl+` toggles the console.
  useEffect(() => {
    if (!ENABLED) return
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && (e.key === '`' || e.code === 'Backquote')) {
        e.preventDefault()
        setOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Connect to the SSE stream only while the console is open.
  useEffect(() => {
    if (!ENABLED || !open) return
    const source = new EventSource('/api/debug/logs')
    source.onmessage = (event) => {
      if (pausedRef.current) return
      try {
        const { source: src, line } = JSON.parse(event.data) as {
          source: 'next' | 'fastapi'
          line: string
        }
        setLogs((prev) => {
          const next = [...prev, { id: idRef.current++, source: src, line }]
          return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next
        })
      } catch {
        // ignore malformed events
      }
    }
    return () => source.close()
  }, [open])

  // Auto-scroll to the newest line unless paused.
  useEffect(() => {
    if (paused) return
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [logs, paused])

  const clear = useCallback(() => setLogs([]), [])

  if (!ENABLED) return null

  return (
    <>
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          title="Open dev logs (Ctrl+`)"
          className="fixed bottom-4 right-4 z-100 flex h-10 w-10 items-center justify-center rounded-full bg-zinc-900 text-zinc-100 shadow-lg ring-1 ring-zinc-700 transition-colors hover:bg-zinc-800"
        >
          <Terminal className="size-5" />
        </button>
      )}

      {open && (
        <div className="fixed inset-x-0 bottom-0 z-100 h-72 border-t border-zinc-700 bg-zinc-950/95 font-mono text-xs text-zinc-300 shadow-2xl backdrop-blur">
          <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-1.5">
            <div className="flex items-center gap-2 text-zinc-400">
              <Terminal className="size-4" />
              <span className="font-semibold">Dev logs</span>
              <span className="text-zinc-600">·</span>
              <span className="text-zinc-500">{logs.length} lines</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPaused((v) => !v)}
                title={paused ? 'Resume' : 'Pause'}
                className="flex h-7 w-7 items-center justify-center rounded hover:bg-zinc-800"
              >
                {paused ? <Play className="size-4" /> : <Pause className="size-4" />}
              </button>
              <button
                type="button"
                onClick={clear}
                title="Clear"
                className="flex h-7 w-7 items-center justify-center rounded hover:bg-zinc-800"
              >
                <Trash2 className="size-4" />
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                title="Close (Ctrl+`)"
                className="flex h-7 w-7 items-center justify-center rounded hover:bg-zinc-800"
              >
                <X className="size-4" />
              </button>
            </div>
          </div>

          <div ref={scrollRef} className="h-[calc(100%-2.5rem)] overflow-auto px-3 py-2">
            {logs.length === 0 ? (
              <p className="text-zinc-600">Waiting for logs…</p>
            ) : (
              logs.map((entry) => (
                <div key={entry.id} className="flex gap-2 whitespace-pre-wrap break-all">
                  <span
                    className={cn(
                      'shrink-0 font-semibold',
                      entry.source === 'fastapi' ? 'text-emerald-400' : 'text-sky-400',
                    )}
                  >
                    [{entry.source === 'fastapi' ? 'api' : 'web'}]
                  </span>
                  <span className={levelClass(entry.line)}>{entry.line}</span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </>
  )
}
