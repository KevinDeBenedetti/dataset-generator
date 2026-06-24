'use client'

import { useState } from 'react'
import { CheckCircle2, Loader2, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { testQaAgent } from '@/api/sdk'
import type { QaAgentTestResponse } from '@/api/types'

// The generated `qa_pairs` is `unknown[]`; this is the shape the agent returns.
interface AgentQaPair {
  question?: string
  answer?: string
  context?: string
}

const SAMPLE_TEXT = `Build simple, secure, scalable systems with Go.
An open-source programming language supported by Google.
Easy to learn and great for teams.
Built-in concurrency and a robust standard library.
Large ecosystem of partners, communities, and tools.`

const LANGUAGES = [
  { value: 'fr', label: 'French' },
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Spanish' },
  { value: 'de', label: 'German' },
]

export default function AgentTestPage() {
  const [text, setText] = useState(SAMPLE_TEXT)
  const [language, setLanguage] = useState('fr')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<QaAgentTestResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await testQaAgent({ text, target_language: language })
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="max-w-3xl mx-auto flex flex-col gap-4 p-4">
      <h1 className="w-full mt-6 mb-1 text-3xl font-bold text-center">
        Verify QA agent
      </h1>
      <p className="text-sm text-muted-foreground text-center mb-2">
        Runs the QA agent on the text below and shows the raw model response and
        the parsed pairs — without the scrape/clean pipeline.
      </p>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste source text…"
        disabled={loading}
        className="w-full min-h-[160px] rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]"
      />

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          disabled={loading}
          className="h-9 rounded-md border bg-transparent px-3 text-sm outline-none focus-visible:border-ring"
        >
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>

        <Button onClick={run} disabled={!text.trim() || loading} className="flex-1">
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <span>Run agent</span>
          )}
        </Button>
      </div>

      {error && <div className="text-red-600 text-sm">{error}</div>}

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              {result.ok ? (
                <CheckCircle2 className="w-5 h-5 text-green-600" />
              ) : (
                <XCircle className="w-5 h-5 text-red-600" />
              )}
              {result.ok ? 'Agent OK' : 'No QA pairs parsed'}
            </CardTitle>
            <div className="flex flex-wrap gap-2 mt-1">
              <Badge variant="secondary">Model: {result.model}</Badge>
              <Badge variant="secondary">Lang: {result.target_language}</Badge>
              <Badge variant="secondary">Pairs: {result.count}</Badge>
              <Badge variant="secondary">Raw: {result.raw_length} chars</Badge>
            </div>
          </CardHeader>

          <CardContent className="flex flex-col gap-4">
            {result.error && (
              <div className="text-red-600 text-sm break-words">
                Error: {result.error}
              </div>
            )}

            <div>
              <p className="text-sm font-medium mb-1">Raw model response</p>
              <ScrollArea className="h-64 rounded-md border bg-muted/30">
                <pre className="p-3 text-xs whitespace-pre-wrap break-words font-mono">
                  {result.raw_response || '(empty response)'}
                </pre>
              </ScrollArea>
            </div>

            {result.qa_pairs && result.qa_pairs.length > 0 && (
              <div>
                <p className="text-sm font-medium mb-1">
                  Parsed Q&amp;A pairs ({result.count})
                </p>
                <div className="space-y-2">
                  {(result.qa_pairs as AgentQaPair[]).map((pair, index) => (
                    <div
                      key={index}
                      className="p-3 border border-gray-200 rounded-md bg-white"
                    >
                      <p className="font-medium text-sm">Q: {pair.question}</p>
                      <p className="mt-1 text-sm text-gray-700">A: {pair.answer}</p>
                      {pair.context && (
                        <p className="mt-1 text-xs text-muted-foreground break-words">
                          Context: {pair.context}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </section>
  )
}
