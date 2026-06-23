import { create } from 'zustand'
import type {
  DatasetResponse,
  DatasetGenerationResponse,
  PipelineStep,
} from '@/api/types'

type GenerationStatus = 'idle' | 'pending' | 'success' | 'error'

interface GenerateState {
  dataset: DatasetResponse | DatasetGenerationResponse | null
  generationStatus: GenerationStatus
  error: string | null
  // Pipeline steps streamed live during generation (before the final result).
  liveSteps: PipelineStep[]

  setDataset: (dataset: DatasetResponse | DatasetGenerationResponse | null) => void
  setGenerationStatus: (status: GenerationStatus) => void
  setError: (error: string | null) => void
  setLiveSteps: (steps: PipelineStep[]) => void
  appendLiveStep: (step: PipelineStep) => void
  resetStatus: () => void
}

export const useGenerateStore = create<GenerateState>((set) => ({
  dataset: null,
  generationStatus: 'idle',
  error: null,
  liveSteps: [],

  setDataset: (dataset) => set({ dataset }),
  setGenerationStatus: (generationStatus) => set({ generationStatus }),
  setError: (error) => set({ error }),
  setLiveSteps: (liveSteps) => set({ liveSteps }),
  appendLiveStep: (step) =>
    set((state) => ({ liveSteps: [...state.liveSteps, step] })),
  resetStatus: () =>
    set({
      generationStatus: 'idle',
      error: null,
      dataset: null,
      liveSteps: [],
    }),
}))
