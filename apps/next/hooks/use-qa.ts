import { useQuery } from '@tanstack/react-query'
import { getQAByDataset, getQAStats } from '@/api/sdk'
import { useQAStore } from '@/stores/qa'

export function useQAByDataset(
  datasetId: string,
  options?: { limit?: number; offset?: number; enabled?: boolean },
) {
  const { setQaItems, setQaResponse, setLoading, setError } = useQAStore()

  return useQuery({
    queryKey: ['qa', datasetId, options?.limit, options?.offset],
    queryFn: async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getQAByDataset(datasetId, {
          limit: options?.limit ?? 10,
          offset: options?.offset ?? 0,
        })
        setQaItems(data.qa_data || [])
        setQaResponse(data)
        return data
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error'
        setError(errorMessage)
        throw err
      } finally {
        setLoading(false)
      }
    },
    enabled: options?.enabled !== false && !!datasetId,
  })
}

// Server-side score aggregation over the whole dataset (accurate on large
// datasets, unlike paging /q_a/{dataset} client-side).
export function useQAStats(
  datasetId: string,
  options?: { scoreThreshold?: number; enabled?: boolean },
) {
  return useQuery({
    queryKey: ['qa-stats', datasetId, options?.scoreThreshold],
    queryFn: () => getQAStats(datasetId, options?.scoreThreshold),
    enabled: options?.enabled !== false && !!datasetId,
  })
}
