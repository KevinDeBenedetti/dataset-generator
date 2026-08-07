'use client'

import { useMemo } from 'react'
import { useParams } from 'next/navigation'
import { DatasetDetail, LoadingState } from '@/components/dataset'
import { useDatasets } from '@/hooks'

export default function DatasetDetailPage() {
  const params = useParams()
  // Datasets are keyed by their Langfuse name (URL-encoded in the route).
  const datasetName = decodeURIComponent(params.id as string)

  const { data: datasets, isPending } = useDatasets()

  const dataset = useMemo(() => {
    return datasets?.find((d) => d.name === datasetName) || null
  }, [datasets, datasetName])

  const pageTitle = dataset?.name || 'Dataset'

  return (
    <section className="max-w-2xl mx-auto flex flex-col gap-4 w-full p-4">
      <h1 className="mt-6 mb-4 text-3xl font-bold text-center">{pageTitle}</h1>

      {isPending && <LoadingState />}

      {!isPending && <DatasetDetail key={dataset?.id} dataset={dataset} />}
    </section>
  )
}
