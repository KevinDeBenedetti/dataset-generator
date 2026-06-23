'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import {
  Database,
  MessagesSquare,
  Gauge,
  Clock,
  Plus,
  ArrowRight,
  Activity,
  FolderOpen,
  BadgeCheck,
  Languages,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useDatasets } from '@/hooks'
import { Sparkline } from './sparkline'
import { cn } from '@/lib/utils'

const WEEKS = 8
const WEEK_MS = 7 * 24 * 60 * 60 * 1000

function relativeTime(dateStr: string | null | undefined, now: number): string {
  if (!dateStr) return '—'
  const t = new Date(dateStr).getTime()
  if (Number.isNaN(t)) return '—'
  const diff = now - t
  const day = 24 * 60 * 60 * 1000
  if (diff < day) return 'today'
  const days = Math.floor(diff / day)
  if (days < 7) return `${days}d ago`
  const weeks = Math.floor(days / 7)
  if (weeks < 5) return `${weeks}w ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.floor(days / 365)}y ago`
}

/** A bento tile — rounded, subtly bordered, hover-lift. */
function Tile({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        'rounded-2xl border bg-card p-5 transition-colors',
        className
      )}
    >
      {children}
    </div>
  )
}

function StatTile({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Database
  label: string
  value: string | number
  hint?: string
}) {
  return (
    <Tile className="flex flex-col justify-between gap-6 hover:bg-accent/30">
      <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="size-5" />
      </div>
      <div>
        <p className="text-3xl font-semibold tracking-tight tabular-nums">
          {value}
        </p>
        <p className="text-sm text-muted-foreground">{label}</p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground/70">{hint}</p>}
      </div>
    </Tile>
  )
}

export function DashboardOverview() {
  const { data: datasets, isLoading, error } = useDatasets()
  // Capture a single render-stable "now" so derived times stay deterministic.
  const [now] = useState(() => Date.now())

  const stats = useMemo(() => {
    const list = datasets ?? []
    const total = list.length
    const totalPairs = list.reduce((sum, d) => sum + (d.qa_sources_count ?? 0), 0)
    const avg = total ? Math.round(totalPairs / total) : 0

    const recent = [...list]
      .sort(
        (a, b) =>
          new Date(b.created_at ?? 0).getTime() -
          new Date(a.created_at ?? 0).getTime()
      )
      .slice(0, 5)

    // Datasets created per week over the last WEEKS weeks (oldest → newest).
    const buckets = Array<number>(WEEKS).fill(0)
    for (const d of list) {
      if (!d.created_at) continue
      const t = new Date(d.created_at).getTime()
      if (Number.isNaN(t)) continue
      const weeksAgo = Math.floor((now - t) / WEEK_MS)
      if (weeksAgo >= 0 && weeksAgo < WEEKS) buckets[WEEKS - 1 - weeksAgo] += 1
    }
    const bucketLabels = buckets.map((_, i) => {
      const ago = WEEKS - 1 - i
      return ago === 0 ? 'this week' : `${ago}w ago`
    })

    // Breakdown by target language (most common first).
    const langMap = new Map<string, number>()
    for (const d of list) {
      const lang = d.target_language || 'unknown'
      langMap.set(lang, (langMap.get(lang) ?? 0) + 1)
    }
    const languages = [...langMap.entries()].sort((a, b) => b[1] - a[1])

    return { total, totalPairs, avg, recent, buckets, bucketLabels, languages }
  }, [datasets, now])

  if (error) {
    return (
      <Tile className="text-center text-sm text-destructive">
        Failed to load dashboard data.
      </Tile>
    )
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-32 rounded-2xl" />
        ))}
        <Skeleton className="h-64 rounded-2xl sm:col-span-2 lg:row-span-2" />
        <Skeleton className="h-28 rounded-2xl sm:col-span-2" />
        <Skeleton className="h-28 rounded-2xl sm:col-span-2" />
      </div>
    )
  }

  const isEmpty = stats.total === 0

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <StatTile
        icon={Database}
        label="Datasets"
        value={stats.total}
      />
      <StatTile
        icon={MessagesSquare}
        label="Q/A pairs"
        value={stats.totalPairs}
      />
      <StatTile
        icon={Gauge}
        label="Avg pairs / dataset"
        value={stats.avg}
      />

      {/* Quick actions tile */}
      <Tile className="flex flex-col justify-between gap-4 bg-primary text-primary-foreground">
        <div className="flex size-9 items-center justify-center rounded-lg bg-primary-foreground/15">
          <Plus className="size-5" />
        </div>
        <div className="flex flex-col gap-2">
          <Button asChild variant="secondary" className="w-full justify-between">
            <Link href="/generate">
              Generate
              <ArrowRight className="size-4" />
            </Link>
          </Button>
          <Link
            href="/datasets"
            className="inline-flex items-center gap-1.5 text-sm text-primary-foreground/80 hover:text-primary-foreground"
          >
            <FolderOpen className="size-4" />
            Browse all datasets
          </Link>
        </div>
      </Tile>

      {/* Recent datasets — the large tile */}
      <Tile className="sm:col-span-2 lg:row-span-2">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="size-4 text-muted-foreground" />
            <h2 className="font-semibold">Recent datasets</h2>
          </div>
          <Link
            href="/datasets"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            View all
          </Link>
        </div>

        {isEmpty ? (
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              No datasets yet. Generate your first one to get started.
            </p>
            <Button asChild size="sm">
              <Link href="/generate">
                Generate a dataset
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          </div>
        ) : (
          <ul className="flex flex-col divide-y">
            {stats.recent.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/datasets/${d.id}`}
                  className="group flex items-center justify-between gap-3 py-3 transition-colors hover:bg-accent/40 -mx-2 px-2 rounded-md"
                >
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {d.name}
                  </span>
                  <span className="shrink-0 tabular-nums text-sm text-muted-foreground">
                    {d.qa_sources_count ?? 0} pairs
                  </span>
                  <span className="w-16 shrink-0 text-right text-xs text-muted-foreground/70">
                    {relativeTime(d.created_at, now)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Tile>

      {/* Activity sparkline */}
      <Tile className="flex flex-col gap-4 sm:col-span-2 hover:bg-accent/30">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="size-4 text-muted-foreground" />
            <h2 className="font-semibold">Activity</h2>
          </div>
          <span className="text-xs text-muted-foreground/70">
            last {WEEKS} weeks
          </span>
        </div>
        <Sparkline values={stats.buckets} labels={stats.bucketLabels} />
      </Tile>

      {/* Latest dataset */}
      <Tile className="flex items-center gap-4 sm:col-span-2 hover:bg-accent/30">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <BadgeCheck className="size-5" />
        </div>
        {isEmpty ? (
          <p className="text-sm text-muted-foreground">No dataset yet</p>
        ) : (
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">Latest dataset</p>
            <Link
              href={`/datasets/${stats.recent[0].id}`}
              className="block truncate font-medium hover:underline"
            >
              {stats.recent[0].name}
            </Link>
            <p className="text-xs text-muted-foreground/70">
              {stats.recent[0].qa_sources_count ?? 0} pairs ·{' '}
              {relativeTime(stats.recent[0].created_at, now)}
            </p>
          </div>
        )}
      </Tile>

      {/* Languages breakdown */}
      <Tile className="flex flex-col gap-3 sm:col-span-2 hover:bg-accent/30">
        <div className="flex items-center gap-2">
          <Languages className="size-4 text-muted-foreground" />
          <h2 className="font-semibold">Languages</h2>
        </div>
        {isEmpty ? (
          <p className="text-sm text-muted-foreground">No datasets yet</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {stats.languages.map(([lang, count]) => (
              <span
                key={lang}
                className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm"
              >
                <span className="font-medium uppercase">{lang}</span>
                <span className="text-muted-foreground tabular-nums">{count}</span>
              </span>
            ))}
          </div>
        )}
      </Tile>
    </div>
  )
}
