import { create } from 'zustand'
import type { DatasetResponse, DatasetGenerationResponse } from '@/api/types'

type GenerationStatus = 'idle' | 'pending' | 'success' | 'error'

interface GenerateState {
  dataset: DatasetResponse | DatasetGenerationResponse | null
  generationStatus: GenerationStatus
  error: string | null

  setDataset: (dataset: DatasetResponse | DatasetGenerationResponse | null) => void
  setGenerationStatus: (status: GenerationStatus) => void
  setError: (error: string | null) => void
  resetStatus: () => void
}

export const useGenerateStore = create<GenerateState>((set) => ({
  dataset: null,
  generationStatus: 'idle',
  error: null,

  setDataset: (dataset) => set({ dataset }),
  setGenerationStatus: (generationStatus) => set({ generationStatus }),
  setError: (error) => set({ error }),
  resetStatus: () =>
    set({
      generationStatus: 'idle',
      error: null,
      dataset: null,
    }),
}))
