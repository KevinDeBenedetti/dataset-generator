import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getDatasets,
  generateDataset,
  deleteDataset,
  analyzeSimilarities,
  cleanSimilarities,
} from '@/api'
import type { DatasetGenerationRequest } from '@/api/types'
import { useDatasetStore } from '@/stores/dataset'
import { useGenerateStore } from '@/stores/generate'

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
  const { setDataset, setGenerationStatus, setError } = useGenerateStore()

  return useMutation({
    mutationFn: async (params: {
      url: string
      name: string
      targetLanguage: string | null
      similarityThreshold: number
    }) => {
      const body: DatasetGenerationRequest = {
        url: params.url,
        dataset_name: params.name,
        target_language: params.targetLanguage,
        similarity_threshold: params.similarityThreshold,
      }
      return generateDataset(body)
    },
    onMutate: () => {
      setGenerationStatus('pending')
      setError(null)
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
