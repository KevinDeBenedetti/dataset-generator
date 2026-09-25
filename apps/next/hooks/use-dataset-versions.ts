import { useQuery } from '@tanstack/react-query'
import { getDatasets, getDatasetVersions, type DatasetVersion } from '@/api/sdk'

export const DATASET_VERSIONS_QUERY_KEY = 'dataset-versions'
export const DATASET_ALL_RUNS_QUERY_KEY = 'dataset-all-runs'

// A single dataset's recorded generations.
export function useDatasetVersions(dataset: string | null | undefined) {
  return useQuery({
    queryKey: [DATASET_VERSIONS_QUERY_KEY, dataset],
    queryFn: () => getDatasetVersions(dataset as string),
    enabled: !!dataset,
    retry: false,
  })
}

export interface DatasetRun extends DatasetVersion {
  dataset: string
}

// Every generation run (version) across every dataset, newest first.
// Powers the /jobs history: each run is one recorded generation.
export function useAllDatasetRuns() {
  return useQuery({
    queryKey: [DATASET_ALL_RUNS_QUERY_KEY],
    queryFn: async (): Promise<DatasetRun[]> => {
      const datasets = await getDatasets()
      const versionLists = await Promise.all(
        datasets.map(async (d) => {
          try {
            return await getDatasetVersions(d.name)
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
    retry: false,
  })
}
