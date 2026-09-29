import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getDatasets,
  getDatasetSources,
  generateDatasetFromFile,
  generateDatasetFromGitHub,
  deleteDataset,
  analyzeSimilarities,
  cleanSimilarities,
  resolvePair,
  exportDatasetToHuggingFace,
  getHuggingFaceDatasets,
  importHuggingFaceDataset,
} from '@/api/sdk'
import { useDatasetStore } from '@/stores/dataset'
import { useGenerateStore } from '@/stores/generate'
import { DATASET_ALL_RUNS_QUERY_KEY } from './use-dataset-versions'

// The /generate form can mine two kinds of source; the mutation branches on it.
export type GenerateParams =
  | {
      source: 'file'
      file: File
      name: string
      targetLanguage: string | null
      similarityThreshold: number
      persist?: boolean
    }
  | {
      source: 'github'
      githubUsername: string
      githubToken?: string | null
      name: string
      targetLanguage: string | null
      similarityThreshold: number
      maxRepos?: number | null
      persist?: boolean
    }

export const DATASETS_QUERY_KEY = ['datasets']

export function useDatasets() {
  const setDatasets = useDatasetStore((state) => state.setDatasets)

  return useQuery({
    queryKey: DATASETS_QUERY_KEY,
    queryFn: async () => {
      const data = await getDatasets()
      setDatasets(data)
      return data
    },
  })
}

export const DATASET_SOURCES_QUERY_KEY = 'dataset-sources'

// The sources a dataset was built from + the history of the analyses that fed
// it. A 404 (unknown dataset) is a definitive answer — don't retry.
export function useDatasetSources(datasetName: string | null | undefined) {
  return useQuery({
    queryKey: [DATASET_SOURCES_QUERY_KEY, datasetName],
    queryFn: () => getDatasetSources(datasetName as string),
    enabled: !!datasetName,
    retry: false,
  })
}

export function useGenerateDataset() {
  const queryClient = useQueryClient()
  const { setDataset, setGenerationStatus, setError, setLiveSteps, setPendingName } =
    useGenerateStore()

  return useMutation({
    mutationFn: async (params: GenerateParams) => {
      if (params.source === 'file') {
        // No streaming variant for file uploads; the final result carries steps.
        return generateDatasetFromFile({
          file: params.file,
          datasetName: params.name,
          targetLanguage: params.targetLanguage,
          similarityThreshold: params.similarityThreshold,
          persist: params.persist,
        })
      }

      return generateDatasetFromGitHub({
        github_username: params.githubUsername,
        github_token: params.githubToken,
        dataset_name: params.name,
        target_language: params.targetLanguage,
        similarity_threshold: params.similarityThreshold,
        max_repos: params.maxRepos,
        persist: params.persist,
      })
    },
    onMutate: (params) => {
      setPendingName(params.name)
      setGenerationStatus('pending')
      setError(null)
      setLiveSteps([])
    },
    onSuccess: (data) => {
      setDataset(data)
      setGenerationStatus('success')
      queryClient.invalidateQueries({ queryKey: DATASETS_QUERY_KEY })
      // A generation adds pairs, sources and a run: the detail page's sources
      // and history, and the /jobs run history, are stale as soon as it lands.
      queryClient.invalidateQueries({ queryKey: [DATASET_SOURCES_QUERY_KEY] })
      queryClient.invalidateQueries({ queryKey: [DATASET_ALL_RUNS_QUERY_KEY] })
    },
    onError: (error) => {
      setError(error instanceof Error ? error.message : 'Failed to generate dataset')
      setGenerationStatus('error')
    },
  })
}

export const HUGGINGFACE_DATASETS_QUERY_KEY = ['huggingface-datasets']

// The dataset repos already on the Hub for the configured account — shown
// alongside the app's own datasets so a user can see what's already exported.
// Not configured (no HF_TOKEN) is a normal, expected state, so don't retry it.
export function useHuggingFaceDatasets() {
  return useQuery({
    queryKey: HUGGINGFACE_DATASETS_QUERY_KEY,
    queryFn: getHuggingFaceDatasets,
    retry: false,
  })
}

// Push a dataset to the Hugging Face Hub (always a private dataset repo).
export function useExportToHuggingFace() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ datasetName, repoId }: { datasetName: string; repoId?: string | null }) =>
      exportDatasetToHuggingFace(datasetName, repoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HUGGINGFACE_DATASETS_QUERY_KEY })
    },
  })
}

// Pull a Hub dataset repo's Q/A pairs into a local dataset — lets quality
// control (and everything else) analyze a dataset that so far only exists on
// the Hub. Invalidates the app's own dataset list, since a successful import
// creates or updates one.
export function useImportHuggingFaceDataset() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ repoId, datasetName }: { repoId: string; datasetName?: string | null }) =>
      importHuggingFaceDataset(repoId, datasetName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DATASETS_QUERY_KEY })
    },
  })
}

export function useDeleteDataset() {
  const queryClient = useQueryClient()
  const removeDataset = useDatasetStore((state) => state.removeDataset)

  return useMutation({
    mutationFn: deleteDataset,
    onSuccess: (_, datasetId) => {
      removeDataset(datasetId)
      queryClient.invalidateQueries({ queryKey: DATASETS_QUERY_KEY })
    },
  })
}

export function useAnalyzeDataset() {
  const { setAnalyzingResult, setAnalyzeStatus, setError } = useDatasetStore()

  return useMutation({
    mutationFn: ({ datasetId, threshold }: { datasetId: string; threshold?: number }) =>
      analyzeSimilarities(datasetId, threshold),
    onMutate: () => {
      setAnalyzeStatus('pending')
      setError(null)
    },
    onSuccess: (data) => {
      setAnalyzingResult(data)
      setAnalyzeStatus('success')
    },
    onError: (error) => {
      setError(error instanceof Error ? error.message : 'Failed to analyze dataset')
      setAnalyzeStatus('error')
    },
  })
}

// Pair-level arbitration: deletes one record of a duplicate pair (admin only).
export function useResolvePair() {
  return useMutation({
    mutationFn: ({ datasetId, removeId }: { datasetId: string; removeId: string }) =>
      resolvePair(datasetId, removeId),
  })
}

export function useCleanDataset() {
  const queryClient = useQueryClient()
  const { setCleaningResult, setCleanStatus, setError } = useDatasetStore()

  return useMutation({
    mutationFn: ({ datasetId, threshold }: { datasetId: string; threshold?: number }) =>
      cleanSimilarities(datasetId, threshold),
    onMutate: () => {
      setCleanStatus('pending')
      setError(null)
    },
    onSuccess: (data) => {
      setCleaningResult(data)
      setCleanStatus('success')
      queryClient.invalidateQueries({ queryKey: DATASETS_QUERY_KEY })
      // Cleaning deletes items, so the per-source pair counts move too.
      queryClient.invalidateQueries({ queryKey: [DATASET_SOURCES_QUERY_KEY] })
    },
    onError: (error) => {
      setError(error instanceof Error ? error.message : 'Failed to clean dataset')
      setCleanStatus('error')
    },
  })
}
