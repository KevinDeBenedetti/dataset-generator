'use client'

import { Suspense, useEffect } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import {
  DatasetGenerate,
  Result,
  GenerationTimeline,
  DatasetAnalyze,
  DatasetClean,
} from '@/components/dataset'
import { useGenerateStore } from '@/stores/generate'
import { useDatasetStore } from '@/stores/dataset'
import { useDatasets } from '@/hooks'

function GenerateContent() {
  const { refetch } = useDatasets()

  // `?dataset=<name>` means "add a source to this dataset" (the CTA on the
  // dataset detail page): generating with an existing name appends to it —
  // new pairs are deduplicated against the existing ones and recorded as the
  // next version.
  const searchParams = useSearchParams()
  const presetDataset = searchParams.get('dataset') ?? ''

  const dataset = useGenerateStore((state) => state.dataset)
  const generationStatus = useGenerateStore((state) => state.generationStatus)
  const liveSteps = useGenerateStore((state) => state.liveSteps)
  const analyzeStatus = useDatasetStore((state) => state.analyzeStatus)
  const analyzingResult = useDatasetStore((state) => state.analyzingResult)
  const cleanStatus = useDatasetStore((state) => state.cleanStatus)
  const cleaningResult = useDatasetStore((state) => state.cleaningResult)

  useEffect(() => {
    refetch()
  }, [refetch])

  return (
    <section className="max-w-2xl mx-auto flex flex-col gap-4 p-4">
      <h1 className="w-full mt-6 mb-4 text-3xl font-bold text-center">
        {presetDataset ? `Add a source to ${presetDataset}` : 'Generate a dataset'}
      </h1>

      {presetDataset && (
        <p className="text-center text-sm text-muted-foreground -mt-2">
          The new pairs are appended to{' '}
          <Link
            href={`/datasets/${encodeURIComponent(presetDataset)}`}
            className="underline font-medium"
          >
            {presetDataset}
          </Link>{' '}
          as a new version.
        </p>
      )}

      <DatasetGenerate initialDatasetName={presetDataset} />

      {generationStatus === 'pending' && liveSteps.length > 0 && (
        <GenerationTimeline steps={liveSteps} />
      )}

      {generationStatus === 'success' && dataset && 'steps' in dataset && (
        <GenerationTimeline steps={dataset.steps ?? []} scrapedContent={dataset.scraped_content} />
      )}

      {generationStatus === 'success' && dataset && (
        <div>
          <h3 className="text-lg font-semibold mb-2">Generated Dataset</h3>
          <Result result={dataset} />
        </div>
      )}

      {analyzeStatus === 'success' && analyzingResult && <DatasetAnalyze />}

      {cleanStatus === 'success' && cleaningResult && <DatasetClean />}
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
