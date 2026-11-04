'use client'

import Link from 'next/link'
import { DatasetsTable, LoadingState, EmptyState } from '@/components/dataset'
import { useDatasets } from '@/hooks'

// Generated datasets that are not on Hugging Face yet. Hugging Face is the
// source of truth: a draft becomes a dataset once it is reviewed and published.
export default function DraftsPage() {
  const { data, isPending, error } = useDatasets()
  const drafts = data ?? []

  return (
    <section className="max-w-3xl mx-auto flex flex-col gap-4 w-full p-4">
      <div className="mt-6 mb-4 text-center">
        <h1 className="text-3xl font-bold">Drafts</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Generated Q/A pairs waiting for review. Open one to check it, then publish it to Hugging
          Face: published datasets are listed under{' '}
          <Link href="/datasets" className="underline underline-offset-2">
            Datasets
          </Link>
          .
        </p>
      </div>

      {isPending && <LoadingState />}

      {!isPending && error && (
        <div className="text-center p-8 text-red-500">
          <p>Error loading drafts</p>
          <p className="text-sm mt-1">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      )}

      {!isPending && !error && drafts.length > 0 && <DatasetsTable datasets={drafts} />}

      {!isPending && !error && drafts.length === 0 && <EmptyState />}
    </section>
  )
}
