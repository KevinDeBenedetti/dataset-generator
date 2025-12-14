'use client'

import { useEffect } from 'react'
import {
  DatasetGenerate,
  Result,
  DatasetAnalyze,
  DatasetClean,
} from '@/components/dataset'
import { useGenerateStore } from '@/stores/generate'
import { useDatasetStore } from '@/stores/dataset'
import { useDatasets } from '@/hooks'

export default function HomePage() {
  const { refetch } = useDatasets()

  const dataset = useGenerateStore((state) => state.dataset)
  const generationStatus = useGenerateStore((state) => state.generationStatus)
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
        Generate a dataset
      </h1>

      <DatasetGenerate />

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
