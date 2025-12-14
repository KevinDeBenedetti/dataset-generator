'use client'

import { DatasetTable, LoadingState, EmptyState } from '@/components/dataset'
import { useDatasets } from '@/hooks'

export default function DatasetsPage() {
  const { data: datasets, isLoading, error } = useDatasets()

  return (
    <section className="max-w-2xl mx-auto flex flex-col gap-4 w-full p-4">
      <h1 className="mt-6 mb-4 text-3xl font-bold text-center">Datasets</h1>

      {isLoading && <LoadingState />}

      {error && (
        <div className="text-center p-8 text-red-500">
          <p>Error loading datasets</p>
        </div>
      )}

      {!isLoading && datasets && datasets.length > 0 && (
        <DatasetTable datasets={datasets} />
      )}

      {!isLoading && (!datasets || datasets.length === 0) && <EmptyState />}
    </section>
  )
}
