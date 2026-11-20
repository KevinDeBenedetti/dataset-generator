'use client'

import Link from 'next/link'
import { useTranslations } from 'next-intl'
import { DatasetsTable, LoadingState, EmptyState } from '@/components/dataset'
import { useDatasets, useDrafts } from '@/hooks'
import { richLink } from '@/lib/rich'

// Generated datasets that are not on Hugging Face yet. Hugging Face is the
// source of truth: a draft becomes a dataset once it is reviewed and published.
function ToReview() {
  const t = useTranslations('drafts')
  const { data, isPending } = useDrafts()
  const drafts = data?.drafts ?? []
  if (isPending) return null
  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold">{t('toReview.title')}</h2>
      {drafts.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('toReview.empty')}</p>
      ) : (
        <ul className="flex flex-col divide-y rounded-lg border">
          {drafts.map((d) => (
            <li key={d.id}>
              <Link
                href={`/drafts/runs/${d.id}`}
                className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-accent/40"
              >
                <span className="min-w-0 flex-1">
                  <span className="block font-medium wrap-anywhere">{d.title}</span>
                  <span className="block font-mono text-xs text-muted-foreground wrap-anywhere">
                    {d.target_repo}
                  </span>
                </span>
                <span className="shrink-0 text-sm text-muted-foreground">
                  {t('toReview.new', { count: d.new })}
                </span>
                <span className="shrink-0 text-sm font-medium">{t('toReview.review')}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function DraftsPage() {
  const t = useTranslations('drafts')
  const tc = useTranslations('common')
  const { data, isPending, error } = useDatasets()
  const drafts = data ?? []

  return (
    <section className="max-w-3xl mx-auto flex flex-col gap-4 w-full py-2 sm:p-4">
      <div className="mt-6 mb-4 text-center">
        <h1 className="text-3xl font-bold">{t('title')}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {t.rich('subtitle', {
            datasets: richLink('/datasets', 'underline underline-offset-2'),
          })}
        </p>
      </div>

      <ToReview />

      <h2 className="mt-4 text-lg font-semibold">{t('local.title')}</h2>
      <p className="-mt-1 text-sm text-muted-foreground">{t('local.description')}</p>

      {isPending && <LoadingState />}

      {!isPending && error && (
        <div className="text-center p-8 text-red-500">
          <p>{t('local.loadError')}</p>
          <p className="text-sm mt-1">
            {error instanceof Error ? error.message : tc('unknownError')}
          </p>
        </div>
      )}

      {!isPending && !error && drafts.length > 0 && <DatasetsTable datasets={drafts} />}

      {!isPending && !error && drafts.length === 0 && <EmptyState />}
    </section>
  )
}
