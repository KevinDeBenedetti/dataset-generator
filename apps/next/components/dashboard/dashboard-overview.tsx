'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import {
  Activity,
  ArrowRight,
  Clock,
  Cloud,
  Database,
  Download,
  FileClock,
  FolderOpen,
  Heart,
  Languages,
  Lock,
  Plus,
  Settings,
} from 'lucide-react'
import { errorStatus } from '@/api/sdk'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { datasetHref } from '@/components/hub'
import { useDatasets, useHubDatasets } from '@/hooks'
import { Sparkline } from './sparkline'
import { cn, relativeTime } from '@/lib/utils'

const WEEKS = 8
const WEEK_MS = 7 * 24 * 60 * 60 * 1000

/** A bento tile — rounded, subtly bordered, hover-lift. */
function Tile({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn('rounded-2xl border bg-card p-4 transition-colors sm:p-5', className)}>
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
    <Tile className="flex flex-col justify-between gap-4 hover:bg-accent/30 sm:gap-6">
      <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="size-5" />
      </div>
      <div>
        <p className="text-2xl font-semibold tracking-tight sm:text-3xl">{value}</p>
        <p className="text-sm text-muted-foreground">{label}</p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground/70">{hint}</p>}
      </div>
    </Tile>
  )
}

// Published datasets come from Hugging Face (the source of truth); drafts —
// generated, not published yet — come from the app's own store.
export function DashboardOverview() {
  const hub = useHubDatasets()
  const drafts = useDatasets()
  // Capture a single render-stable "now" so derived times stay deterministic.
  const [now] = useState(() => Date.now())
  const hubStatus = errorStatus(hub.error)

  const published = useMemo(() => {
    const list = hub.data?.datasets ?? []
    const recent = list
      .toSorted(
        (a, b) =>
          new Date(b.last_modified ?? 0).getTime() - new Date(a.last_modified ?? 0).getTime(),
      )
      .slice(0, 6)
    const languages = new Map<string, number>()
    for (const d of list) {
      for (const lang of d.language ?? ['unknown']) {
        languages.set(lang, (languages.get(lang) ?? 0) + 1)
      }
    }
    return {
      total: list.length,
      private: list.filter((d) => d.private).length,
      downloads: list.reduce((sum, d) => sum + (d.downloads ?? 0), 0),
      likes: list.reduce((sum, d) => sum + (d.likes ?? 0), 0),
      recent,
      languages: [...languages.entries()].toSorted((a, b) => b[1] - a[1]),
    }
  }, [hub.data])

  const pending = useMemo(() => {
    const list = drafts.data ?? []
    // Drafts created per week over the last WEEKS weeks (oldest → newest).
    const buckets = Array<number>(WEEKS).fill(0)
    for (const d of list) {
      if (!d.created_at) continue
      const t = new Date(d.created_at).getTime()
      if (Number.isNaN(t)) continue
      const weeksAgo = Math.floor((now - t) / WEEK_MS)
      if (weeksAgo >= 0 && weeksAgo < WEEKS) buckets[WEEKS - 1 - weeksAgo] += 1
    }
    const labels = buckets.map((_, i) => {
      const ago = WEEKS - 1 - i
      return ago === 0 ? 'this week' : `${ago}w ago`
    })
    const recent = list
      .toSorted(
        (a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime(),
      )
      .slice(0, 4)
    return { total: list.length, buckets, labels, recent }
  }, [drafts.data, now])

  if (hub.isPending && drafts.isPending) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        {['a', 'b', 'c', 'd'].map((key) => (
          <Skeleton key={key} className="h-32 rounded-2xl" />
        ))}
        <Skeleton className="h-64 rounded-2xl col-span-2 lg:row-span-2" />
        <Skeleton className="h-28 rounded-2xl col-span-2" />
        <Skeleton className="h-28 rounded-2xl col-span-2" />
      </div>
    )
  }

  const connected = !hub.error

  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
      {connected ? (
        <>
          <StatTile
            icon={Database}
            label="Datasets on Hugging Face"
            value={hub.isPending ? '…' : published.total}
            hint={hub.data ? `${hub.data.namespace} · ${published.private} private` : undefined}
          />
          <StatTile
            icon={Download}
            label="Downloads"
            value={hub.isPending ? '…' : published.downloads}
            hint="last 30 days"
          />
        </>
      ) : (
        <Tile className="flex flex-col justify-between gap-4 col-span-2">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Cloud className="size-5" />
          </div>
          <div>
            <p className="font-semibold">
              {hubStatus === 503 ? 'Connect Hugging Face' : "Hugging Face didn't answer"}
            </p>
            <p className="text-sm text-muted-foreground">
              {hubStatus === 503
                ? 'Your datasets are read straight from the Hub, with your own token.'
                : hub.error instanceof Error
                  ? hub.error.message
                  : 'Try again in a moment.'}
            </p>
          </div>
          {hubStatus === 503 && (
            <Button asChild size="sm" variant="outline" className="self-start">
              <Link href="/settings">
                <Settings className="size-4" />
                Add your token in Settings
              </Link>
            </Button>
          )}
        </Tile>
      )}
      <StatTile
        icon={FileClock}
        label="Drafts to review"
        value={drafts.isPending ? '…' : pending.total}
        hint="generated, not published yet"
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
            className="-mx-2 inline-flex items-center gap-1.5 px-2 py-2 text-sm text-primary-foreground/80 hover:text-primary-foreground"
          >
            <FolderOpen className="size-4" />
            Browse datasets
          </Link>
        </div>
      </Tile>

      {/* Recently updated on the Hub — the large tile */}
      <Tile className="col-span-2 lg:row-span-2">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="size-4 text-muted-foreground" />
            <h2 className="font-semibold">Recently updated datasets</h2>
          </div>
          <Link
            href="/datasets"
            className="-m-2 p-2 text-sm text-muted-foreground hover:text-foreground"
          >
            View all
          </Link>
        </div>

        {!connected ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            Connect Hugging Face to see your datasets here.
          </p>
        ) : hub.isPending ? (
          <Skeleton className="h-40 rounded-xl" />
        ) : published.total === 0 ? (
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              Nothing published yet. Generate Q/A pairs, review the draft, then publish it.
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
            {published.recent.map((d) => (
              <li key={d.id}>
                <Link
                  href={datasetHref(d.id)}
                  className="group flex items-center justify-between gap-3 py-3 transition-colors hover:bg-accent/40 -mx-2 px-2 rounded-md"
                >
                  <span className="min-w-0 flex-1 font-medium inline-flex items-center gap-1.5">
                    {d.private && <Lock className="size-3 shrink-0 text-muted-foreground" />}
                    <span className="min-w-0 wrap-anywhere">{d.pretty_name || d.id}</span>
                  </span>
                  <span className="shrink-0 text-sm text-muted-foreground">
                    {d.size_category ?? ''}
                  </span>
                  <span className="w-16 shrink-0 text-right text-xs text-muted-foreground/70">
                    {relativeTime(d.last_modified, now)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Tile>

      {/* Drafts waiting for review */}
      <Tile className="flex flex-col gap-3 col-span-2 hover:bg-accent/30">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileClock className="size-4 text-muted-foreground" />
            <h2 className="font-semibold">Waiting for review</h2>
          </div>
          <Link
            href="/drafts"
            className="-m-2 p-2 text-sm text-muted-foreground hover:text-foreground"
          >
            All drafts
          </Link>
        </div>
        {pending.recent.length === 0 ? (
          <p className="text-sm text-muted-foreground">No draft waiting.</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {pending.recent.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/drafts/${encodeURIComponent(d.name)}`}
                  className="flex items-center justify-between gap-3 py-2 -mx-2 px-2 rounded-md hover:bg-accent/40"
                >
                  <span className="min-w-0 flex-1 font-medium wrap-anywhere">{d.name}</span>
                  <span className="shrink-0 text-sm text-muted-foreground">
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

      {/* Generation activity */}
      <Tile className="flex flex-col gap-4 col-span-2 hover:bg-accent/30">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="size-4 text-muted-foreground" />
            <h2 className="font-semibold">Drafts generated</h2>
          </div>
          <span className="text-xs text-muted-foreground/70">last {WEEKS} weeks</span>
        </div>
        <Sparkline values={pending.buckets} labels={pending.labels} />
      </Tile>

      {/* Languages of the published datasets */}
      {connected && published.total > 0 && (
        <Tile className="flex flex-col gap-3 col-span-2 hover:bg-accent/30">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Languages className="size-4 text-muted-foreground" />
              <h2 className="font-semibold">Languages</h2>
            </div>
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/70">
              <Heart className="size-3" />
              {published.likes} likes
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {published.languages.map(([lang, count]) => (
              <span
                key={lang}
                className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm"
              >
                <span className="font-medium uppercase">{lang}</span>
                <span className="text-muted-foreground tabular-nums">{count}</span>
              </span>
            ))}
          </div>
        </Tile>
      )}
    </div>
  )
}
