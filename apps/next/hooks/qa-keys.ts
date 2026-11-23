import type { QueryClient } from '@tanstack/react-query'

// The query keys of a dataset's Q&A views: its pairs, page by page, and its
// score statistics (the Quality page).
export const qaKey = (datasetId: string, limit?: number, offset?: number) =>
  ['qa', datasetId, limit, offset] as const

export const qaStatsKey = (datasetId: string, scoreThreshold?: number) =>
  ['qa-stats', datasetId, scoreThreshold] as const

/** After anything that changes a dataset's pairs (scoring, cleaning,
 *  resolving a duplicate): every view built on them is fetched again. */
export async function invalidateDatasetQA(client: QueryClient, datasetId: string): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: ['qa-stats', datasetId] }),
    client.invalidateQueries({ queryKey: ['qa', datasetId] }),
  ])
}
