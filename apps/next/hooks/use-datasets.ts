import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getDatasets,
  generateDatasetStream,
  generateDatasetFromFile,
  generateDatasetFromGitHub,
  deleteDataset,
  analyzeSimilarities,
  cleanSimilarities,
} from '@/api/sdk'
import type { DatasetGenerationRequest } from '@/api/types'
import { useDatasetStore } from '@/stores/dataset'
import { useGenerateStore } from '@/stores/generate'

// The /generate form can mine three kinds of source; the mutation branches on it.
export type GenerateParams =
  | {
      source: 'url'
      url: string
      name: string
      targetLanguage: string | null
      similarityThreshold: number
      crawl?: boolean
      maxDepth?: number | null
      maxPages?: number | null
      syncLangfuse?: boolean
    }
  | {
      source: 'file'
      file: File
      name: string
      targetLanguage: string | null
      similarityThreshold: number
      syncLangfuse?: boolean
    }
  | {
      source: 'github'
      githubUsername: string
      githubToken?: string | null
      name: string
      targetLanguage: string | null
      similarityThreshold: number
      maxRepos?: number | null
      syncLangfuse?: boolean
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

export function useGenerateDataset() {
  const queryClient = useQueryClient()
  const { setDataset, setGenerationStatus, setError, setLiveSteps, appendLiveStep } =
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
          syncLangfuse: params.syncLangfuse,
        })
      }

      if (params.source === 'github') {
        return generateDatasetFromGitHub({
          github_username: params.githubUsername,
          github_token: params.githubToken,
          dataset_name: params.name,
          target_language: params.targetLanguage,
          similarity_threshold: params.similarityThreshold,
          max_repos: params.maxRepos,
          sync_langfuse: params.syncLangfuse,
        })
      }

      const body: DatasetGenerationRequest = {
        url: params.url,
        dataset_name: params.name,
        target_language: params.targetLanguage,
        similarity_threshold: params.similarityThreshold,
        crawl: params.crawl,
        max_depth: params.maxDepth,
        max_pages: params.maxPages,
        sync_langfuse: params.syncLangfuse,
      }
      // Stream pipeline progress so the timeline fills in live.
      return generateDatasetStream(body, {
        onStep: (step) => appendLiveStep(step),
      })
    },
    onMutate: () => {
      setGenerationStatus('pending')
      setError(null)
      setLiveSteps([])
    },
    onSuccess: (data) => {
      setDataset(data)
      setGenerationStatus('success')
      queryClient.invalidateQueries({ queryKey: DATASETS_QUERY_KEY })
    },
    onError: (error) => {
      setError(error instanceof Error ? error.message : 'Failed to generate dataset')
      setGenerationStatus('error')
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
    mutationFn: (datasetId: string) => analyzeSimilarities(datasetId),
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

export function useCleanDataset() {
  const queryClient = useQueryClient()
  const { setCleaningResult, setCleanStatus, setError } = useDatasetStore()

  return useMutation({
    mutationFn: (datasetId: string) => cleanSimilarities(datasetId),
    onMutate: () => {
      setCleanStatus('pending')
      setError(null)
    },
    onSuccess: (data) => {
      setCleaningResult(data)
      setCleanStatus('success')
      queryClient.invalidateQueries({ queryKey: DATASETS_QUERY_KEY })
    },
    onError: (error) => {
      setError(error instanceof Error ? error.message : 'Failed to clean dataset')
      setCleanStatus('error')
    },
  })
}
