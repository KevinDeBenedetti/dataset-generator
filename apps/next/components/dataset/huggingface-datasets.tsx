'use client'

import type { ComponentType } from 'react'
import {
  CalendarDays,
  Download,
  ExternalLink,
  FileText,
  Globe,
  HardDrive,
  Heart,
  Lock,
  ShieldAlert,
} from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useHuggingFaceDatasets } from '@/hooks'
import type { HuggingFaceDataset } from '@/api/sdk'

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString()
}

function formatNumber(value?: number | null): string | null {
  if (value == null) return null
  return new Intl.NumberFormat().format(value)
}

function formatBytes(value?: number | null): string | null {
  if (value == null) return null
  if (value === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const size = value / 1024 ** exponent
  return `${exponent === 0 ? size : size.toFixed(1)} ${units[exponent]}`
}

// One metadata pair (icon + label), skipped entirely when there's nothing to show.
function Stat({
  icon: Icon,
  label,
}: {
  icon: ComponentType<{ className?: string }>
  label: string | null
}) {
  if (label == null) return null
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground">
      <Icon className="size-3.5" />
      {label}
    </span>
  )
}

function HuggingFaceDatasetCard({ dataset }: { dataset: HuggingFaceDataset }) {
  const title = dataset.pretty_name || dataset.id
  const sizeLabel = [dataset.size_category, formatBytes(dataset.used_storage)]
    .filter(Boolean)
    .join(' · ')

  return (
    <Card className="py-4 gap-3">
      <CardHeader className="px-4 gap-1">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base">
            <a
              href={dataset.url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline inline-flex items-center gap-1"
            >
              {title}
              <ExternalLink className="size-3.5 text-muted-foreground shrink-0" />
            </a>
          </CardTitle>
          <div className="flex items-center gap-1 shrink-0">
            {dataset.private && (
              <Badge variant="secondary" className="gap-1">
                <Lock className="size-3" />
                Private
              </Badge>
            )}
            {!dataset.private && <Badge variant="outline">Public</Badge>}
            {dataset.gated && (
              <Badge variant="destructive" className="gap-1">
                <ShieldAlert className="size-3" />
                Gated{typeof dataset.gated === 'string' ? ` (${dataset.gated})` : ''}
              </Badge>
            )}
          </div>
        </div>
        {dataset.pretty_name && (
          <p className="text-xs text-muted-foreground font-mono">{dataset.id}</p>
        )}
        {dataset.description && (
          <CardDescription className="line-clamp-2">{dataset.description}</CardDescription>
        )}
      </CardHeader>

      <CardContent className="px-4 flex flex-col gap-2">
        {dataset.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {dataset.tags.map((tag) => (
              <Badge key={tag} variant="outline" className="text-xs font-normal">
                {tag}
              </Badge>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
          <Stat icon={Download} label={formatNumber(dataset.downloads)} />
          <Stat icon={Heart} label={formatNumber(dataset.likes)} />
          <Stat
            icon={FileText}
            label={dataset.file_count != null ? `${dataset.file_count} file(s)` : null}
          />
          <Stat icon={HardDrive} label={sizeLabel || null} />
          <Stat icon={Globe} label={dataset.language?.join(', ') ?? null} />
          <Stat icon={CalendarDays} label={`Updated ${formatDate(dataset.last_modified)}`} />
        </div>

        {(dataset.author || dataset.license) && (
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {dataset.author && <span>by {dataset.author}</span>}
            {dataset.license && <span>{dataset.license} license</span>}
            {dataset.created_at && <span>created {formatDate(dataset.created_at)}</span>}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// Shown on the datasets page as a read-only companion to the app's own
// datasets — the repos that already exist on the Hub for the configured
// account, with the full metadata the Hub exposes (card, tags, storage, …).
// Not configured (no HF_TOKEN) is a normal, silent state: nothing renders
// rather than surfacing a 503 as an error.
export function HuggingFaceDatasets() {
  const { data, isPending, error } = useHuggingFaceDatasets()

  if (isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  if (error) {
    return null
  }

  const datasets = data?.datasets ?? []
  if (datasets.length === 0) {
    return null
  }

  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold">
        On Hugging Face
        <span className="text-muted-foreground font-normal ml-2 text-sm">
          {data?.namespace} · {datasets.length} dataset(s)
        </span>
      </h2>
      <div className="flex flex-col gap-3">
        {datasets.map((dataset) => (
          <HuggingFaceDatasetCard key={dataset.id} dataset={dataset} />
        ))}
      </div>
    </div>
  )
}
