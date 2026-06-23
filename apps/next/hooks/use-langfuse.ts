import { useMutation, useQuery } from '@tanstack/react-query'
import { exportToLangfuse, getLangfuseVersions } from '@/api'
import { useLangfuseStore } from '@/stores/langfuse'

export const LANGFUSE_VERSIONS_QUERY_KEY = 'langfuse-versions'

export function useLangfuseVersions(dataset: string | null | undefined) {
  return useQuery({
    queryKey: [LANGFUSE_VERSIONS_QUERY_KEY, dataset],
    queryFn: () => getLangfuseVersions(dataset as string),
    enabled: !!dataset,
    // Langfuse may not be configured (503) — don't retry or spam errors.
    retry: false,
  })
}

export function useExportToLangfuse() {
  const { setLoading, setError } = useLangfuseStore()

  return useMutation({
    mutationFn: ({
      datasetName,
      langfuseDatasetName,
    }: {
      datasetName: string
      langfuseDatasetName?: string | null
    }) => exportToLangfuse(datasetName, langfuseDatasetName),
    onMutate: () => {
      setLoading(true)
      setError(null)
    },
    onSuccess: () => {
      setLoading(false)
    },
    onError: (error) => {
      setError(error instanceof Error ? error.message : 'Export failed')
      setLoading(false)
    },
  })
}
