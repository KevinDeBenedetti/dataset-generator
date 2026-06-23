import { cn } from '@/lib/utils'

/**
 * Minimal dependency-free bar sparkline. Heights are normalised to the series
 * max; empty buckets keep a faint baseline so the rhythm stays readable.
 */
export function Sparkline({
  values,
  labels,
  className,
}: {
  values: number[]
  labels?: string[]
  className?: string
}) {
  const max = Math.max(1, ...values)

  return (
    <div className={cn('flex h-20 items-stretch gap-1.5', className)}>
      {values.map((value, index) => (
        <div
          key={index}
          className="flex flex-1 flex-col justify-end overflow-hidden rounded-sm bg-primary/10"
          title={labels?.[index] ? `${labels[index]}: ${value}` : `${value}`}
        >
          <div
            className="rounded-sm bg-primary/70 transition-colors hover:bg-primary"
            style={{ height: `${Math.max(4, (value / max) * 100)}%` }}
          />
        </div>
      ))}
    </div>
  )
}
