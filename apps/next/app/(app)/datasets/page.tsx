'use client'

import { DatasetsTable, LoadingState, EmptyState } from '@/components/dataset'
import { useDatasets } from '@/hooks'

export default function DatasetsPage() {
  const { data, isPending, error } = useDatasets()
  const datasets = data ?? []

  return (
    <section className="max-w-3xl mx-auto flex flex-col gap-4 w-full p-4">
      <h1 className="mt-6 mb-4 text-3xl font-bold text-center">Datasets</h1>

      {isPending && <LoadingState />}

      {!isPending && error && (
        <div className="text-center p-8 text-red-500">
          <p>Error loading datasets</p>
          <p className="text-sm mt-1">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      )}

      {!isPending && !error && datasets.length > 0 && <DatasetsTable datasets={datasets} />}

      {!isPending && !error && datasets.length === 0 && <EmptyState />}
    </section>
  )
}
