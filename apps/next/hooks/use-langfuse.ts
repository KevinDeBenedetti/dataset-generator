import { useMutation, useQuery } from '@tanstack/react-query'
import {
  exportToLangfuse,
  getLangfuseVersions,
  getLangfuseDatasets,
  type LangfuseVersion,
} from '@/api/sdk'
import { useLangfuseStore } from '@/stores/langfuse'

export const LANGFUSE_VERSIONS_QUERY_KEY = 'langfuse-versions'
export const LANGFUSE_DATASETS_QUERY_KEY = 'langfuse-datasets'
export const LANGFUSE_ALL_RUNS_QUERY_KEY = 'langfuse-all-runs'

// All datasets present in Langfuse. Returns null-ish on 503 (not configured).
export function useLangfuseDatasets() {
  return useQuery({
    queryKey: [LANGFUSE_DATASETS_QUERY_KEY],
    queryFn: getLangfuseDatasets,
    // Langfuse may not be configured (503) — don't retry or spam errors.
    retry: false,
  })
}

export function useLangfuseVersions(dataset: string | null | undefined) {
  return useQuery({
    queryKey: [LANGFUSE_VERSIONS_QUERY_KEY, dataset],
    queryFn: () => getLangfuseVersions(dataset as string),
    enabled: !!dataset,
    // Langfuse may not be configured (503) — don't retry or spam errors.
    retry: false,
  })
}

export interface DatasetRun extends LangfuseVersion {
  dataset: string
}

// Every generation run (version) across every Langfuse dataset, newest first.
// Powers the /jobs history: each run is one recorded generation.
export function useAllDatasetRuns() {
  return useQuery({
    queryKey: [LANGFUSE_ALL_RUNS_QUERY_KEY],
    queryFn: async (): Promise<DatasetRun[]> => {
      const { datasets } = await getLangfuseDatasets()
      const versionLists = await Promise.all(
        datasets.map(async (d) => {
          try {
            return await getLangfuseVersions(d.name)
          } catch {
            // One dataset without readable runs shouldn't sink the whole view.
            return { dataset_name: d.name, total: 0, versions: [] }
          }
        }),
      )
      const runs = versionLists.flatMap((list) =>
        list.versions.map((v) => ({ ...v, dataset: list.dataset_name })),
      )
      runs.sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
      return runs
    },
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
