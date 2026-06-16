'use client'

import { useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  FileText,
  XCircle,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import type { PipelineStep, PipelineStepStatus } from '@/api/types'

const STATUS_CONFIG: Record<
  PipelineStepStatus,
  { icon: typeof CheckCircle2; color: string }
> = {
  success: { icon: CheckCircle2, color: 'text-green-600' },
  warning: { icon: AlertTriangle, color: 'text-amber-500' },
  error: { icon: XCircle, color: 'text-red-600' },
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

interface GenerationTimelineProps {
  steps: PipelineStep[]
  scrapedContent?: string | null
}

export function GenerationTimeline({
  steps,
  scrapedContent,
}: GenerationTimelineProps) {
  const [showContent, setShowContent] = useState(false)

  if (!steps?.length) {
    return null
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Pipeline</CardTitle>
      </CardHeader>

      <CardContent>
        <ol className="relative">
          {steps.map((step, index) => {
            const config = STATUS_CONFIG[step.status] ?? STATUS_CONFIG.success
            const Icon = config.icon
            const isLast = index === steps.length - 1

            return (
              <li key={step.key} className="relative pl-9 pb-5 last:pb-0">
                {!isLast && (
                  <span className="absolute left-[13px] top-7 bottom-0 w-px bg-border" />
                )}
                <span
                  className={cn(
                    'absolute left-0 top-0 flex items-center justify-center bg-card',
                    config.color
                  )}
                >
                  <Icon className="w-[26px] h-[26px]" />
                </span>

                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-sm font-medium">{step.label}</p>
                  <span className="text-xs text-muted-foreground tabular-nums shrink-0">
                    {formatDuration(step.duration_ms)}
                  </span>
                </div>
                {step.detail && (
                  <p className="mt-0.5 text-xs text-muted-foreground break-words">
                    {step.detail}
                  </p>
                )}
              </li>
            )
          })}
        </ol>

        {scrapedContent ? (
          <div className="mt-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-muted-foreground"
              onClick={() => setShowContent((value) => !value)}
            >
              <FileText className="w-3.5 h-3.5" />
              {showContent ? 'Hide' : 'View'} scraped content
              <ChevronDown
                className={cn(
                  'w-3.5 h-3.5 transition-transform',
                  showContent && 'rotate-180'
                )}
              />
            </Button>

            {showContent && (
              <ScrollArea className="mt-2 h-64 rounded-md border bg-muted/30">
                <pre className="p-3 text-xs whitespace-pre-wrap break-words font-mono">
                  {scrapedContent}
                </pre>
              </ScrollArea>
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
