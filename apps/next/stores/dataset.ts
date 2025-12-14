import { create } from 'zustand'
import type {
  DatasetResponse,
  SimilarityAnalysisResponse,
  CleanSimilarityResponse,
} from '@/api/types'

type OperationStatus = 'idle' | 'pending' | 'success' | 'error'

interface DatasetState {
  datasets: DatasetResponse[]
  dataset: DatasetResponse | null
  loading: boolean
  error: string | null

  analyzingResult: SimilarityAnalysisResponse | null
  cleaningResult: CleanSimilarityResponse | null
  analyzeStatus: OperationStatus
  cleanStatus: OperationStatus

  setDatasets: (datasets: DatasetResponse[]) => void
  setDataset: (dataset: DatasetResponse | null) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  setAnalyzingResult: (result: SimilarityAnalysisResponse | null) => void
  setCleaningResult: (result: CleanSimilarityResponse | null) => void
  setAnalyzeStatus: (status: OperationStatus) => void
  setCleanStatus: (status: OperationStatus) => void
  removeDataset: (datasetId: string) => void
  resetStatus: () => void
}

export const useDatasetStore = create<DatasetState>((set) => ({
  datasets: [],
  dataset: null,
  loading: false,
  error: null,

  analyzingResult: null,
  cleaningResult: null,
  analyzeStatus: 'idle',
  cleanStatus: 'idle',

  setDatasets: (datasets) => set({ datasets }),
  setDataset: (dataset) => set({ dataset }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  setAnalyzingResult: (analyzingResult) => set({ analyzingResult }),
  setCleaningResult: (cleaningResult) => set({ cleaningResult }),
  setAnalyzeStatus: (analyzeStatus) => set({ analyzeStatus }),
  setCleanStatus: (cleanStatus) => set({ cleanStatus }),
  removeDataset: (datasetId) =>
    set((state) => ({
      datasets: state.datasets.filter((d) => d.id !== datasetId),
      dataset: state.dataset?.id === datasetId ? null : state.dataset,
    })),
  resetStatus: () =>
    set({
      analyzeStatus: 'idle',
      cleanStatus: 'idle',
      error: null,
      analyzingResult: null,
      cleaningResult: null,
    }),
}))
