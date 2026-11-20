'use client'

import { Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { DatasetGenerate, Result, GenerationTimeline, RecentRuns } from '@/components/dataset'
import { useGenerateStore } from '@/stores/generate'
import { richLink } from '@/lib/rich'

function GenerateContent() {
  const t = useTranslations('generate.page')
  // `?target=<owner/name>` pre-fills the Hugging Face dataset the draft adds
  // to (the "Add data" button of a dataset page).
  const searchParams = useSearchParams()
  const presetTarget = searchParams.get('target') ?? ''
  const dataset = useGenerateStore((state) => state.dataset)
  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const liveSteps = useGenerateStore((state) => state.liveSteps)
  const draftId = dataset && 'draft_run_id' in dataset ? dataset.draft_run_id : null

  return (
    <section className="max-w-3xl mx-auto flex flex-col gap-4 py-2 sm:p-4">
      <h1 className="w-full mt-6 mb-4 text-3xl font-bold text-center wrap-anywhere">
        {presetTarget ? t('addDataTo', { target: presetTarget }) : t('title')}
      </h1>

      <DatasetGenerate initialTarget={presetTarget} />

      {generationStatus === 'pending' && liveSteps.length > 0 && (
        <GenerationTimeline steps={liveSteps} />
      )}

      {generationStatus === 'success' && dataset && 'steps' in dataset && (
        <GenerationTimeline steps={dataset.steps ?? []} scrapedContent={dataset.scraped_content} />
      )}

      {generationStatus === 'success' && draftId && (
        <div className="rounded-lg border p-4 flex items-center justify-between gap-3 flex-wrap">
          <span className="text-sm">{t('draftReady')}</span>
          <Link
            href={`/drafts/runs/${draftId}`}
            className="inline-flex items-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          >
            {t('reviewDraft')}
          </Link>
        </div>
      )}

      {generationStatus === 'success' && dataset && (
        <div>
          <h3 className="text-lg font-semibold mb-2">{t('generatedDataset')}</h3>
          <Result result={dataset} />
        </div>
      )}

      <p className="text-center text-xs text-muted-foreground">
        {t.rich('footnote', {
          github: richLink('/github', 'underline'),
          quality: richLink('/quality', 'underline'),
        })}
      </p>

      <RecentRuns />
    </section>
  )
}

export default function GeneratePage() {
  const t = useTranslations('generate.page')
  // useSearchParams() opts the subtree into client-side rendering; Next requires
  // it to sit under a Suspense boundary so the rest of the page can prerender.
  return (
    <Suspense
      fallback={
        <section className="max-w-2xl mx-auto flex flex-col gap-4 py-2 sm:p-4">
          <h1 className="w-full mt-6 mb-4 text-3xl font-bold text-center">{t('title')}</h1>
        </section>
      }
    >
      <GenerateContent />
    </Suspense>
  )
}
