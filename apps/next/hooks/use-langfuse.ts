import { useMutation } from '@tanstack/react-query'
import { exportToLangfuse } from '@/api'
import { useLangfuseStore } from '@/stores/langfuse'

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
