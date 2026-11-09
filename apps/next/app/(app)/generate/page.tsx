'use client'

import { Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { DatasetGenerate, Result, GenerationTimeline, RecentRuns } from '@/components/dataset'
import { useGenerateStore } from '@/stores/generate'

function GenerateContent() {
  // `?target=<owner/name>` pre-fills the Hugging Face dataset the draft adds
  // to (the "Add data" button of a dataset page).
  const searchParams = useSearchParams()
  const presetTarget = searchParams.get('target') ?? ''
  const dataset = useGenerateStore((state) => state.dataset)
  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const liveSteps = useGenerateStore((state) => state.liveSteps)
  const draftId = dataset && 'draft_run_id' in dataset ? dataset.draft_run_id : null

  return (
    <section className="max-w-3xl mx-auto flex flex-col gap-4 p-4">
      <h1 className="w-full mt-6 mb-4 text-3xl font-bold text-center">
        {presetTarget ? `Add data to ${presetTarget}` : 'Generate a dataset'}
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
          <span className="text-sm">
            Draft ready: review the pairs before they go to Hugging Face.
          </span>
          <Link
            href={`/drafts/runs/${draftId}`}
            className="inline-flex items-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          >
            Review the draft
          </Link>
        </div>
      )}

      {generationStatus === 'success' && dataset && (
        <div>
          <h3 className="text-lg font-semibold mb-2">Generated Dataset</h3>
          <Result result={dataset} />
        </div>
      )}

      <p className="text-center text-xs text-muted-foreground">
        Datasets from your GitHub account (Q&amp;A pairs, the knowledge corpus) are generated on the{' '}
        <Link href="/github" className="underline">
          GitHub page
        </Link>
        ; duplicates across a dataset are analysed and cleaned on{' '}
        <Link href="/quality" className="underline">
          Quality control
        </Link>
        .
      </p>

      <RecentRuns />
    </section>
  )
}

export default function GeneratePage() {
  // useSearchParams() opts the subtree into client-side rendering; Next requires
  // it to sit under a Suspense boundary so the rest of the page can prerender.
  return (
    <Suspense
      fallback={
        <section className="max-w-2xl mx-auto flex flex-col gap-4 p-4">
          <h1 className="w-full mt-6 mb-4 text-3xl font-bold text-center">Generate a dataset</h1>
        </section>
      }
    >
      <GenerateContent />
    </Suspense>
  )
}
