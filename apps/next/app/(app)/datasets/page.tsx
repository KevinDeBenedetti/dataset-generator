'use client'

import { LangfuseDatasetTable, LoadingState, EmptyState } from '@/components/dataset'
import { useLangfuseDatasets } from '@/hooks'

export default function DatasetsPage() {
  const { data, isPending, error } = useLangfuseDatasets()
  const datasets = data?.datasets ?? []

  // The wrapper throws "Langfuse is not configured" on a 503 — surface that
  // distinctly from a real upstream failure.
  const notConfigured = error instanceof Error && /not configured/i.test(error.message)

  return (
    <section className="max-w-3xl mx-auto flex flex-col gap-4 w-full p-4">
      <h1 className="mt-6 mb-4 text-3xl font-bold text-center">Langfuse datasets</h1>

      {isPending && <LoadingState />}

      {!isPending && notConfigured && (
        <div className="text-center p-8 text-muted-foreground">
          <p>Langfuse is not configured.</p>
          <p className="text-sm mt-1">
            Set <code>LANGFUSE_SECRET_KEY</code>, <code>LANGFUSE_PUBLIC_KEY</code> and{' '}
            <code>LANGFUSE_HOST</code> in your <code>.env</code> to see your datasets here.
          </p>
        </div>
      )}

      {!isPending && error && !notConfigured && (
        <div className="text-center p-8 text-red-500">
          <p>Error loading datasets from Langfuse</p>
          <p className="text-sm mt-1">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      )}

      {!isPending && !error && datasets.length > 0 && <LangfuseDatasetTable datasets={datasets} />}

      {!isPending && !error && datasets.length === 0 && <EmptyState />}
    </section>
  )
}
