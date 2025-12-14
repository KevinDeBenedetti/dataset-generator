import { create } from 'zustand'
import type { QaItem, QaListResponse } from '@/api/types'

interface QAState {
  qaItems: QaItem[]
  qaResponse: QaListResponse | null
  currentQuestion: string | null
  currentAnswer: string | null
  loading: boolean
  error: string | null

  setQaItems: (items: QaItem[]) => void
  appendQaItems: (items: QaItem[]) => void
  setQaResponse: (response: QaListResponse | null) => void
  setCurrentQuestion: (question: string | null) => void
  setCurrentAnswer: (answer: string | null) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  reset: () => void
}

export const useQAStore = create<QAState>((set) => ({
  qaItems: [],
  qaResponse: null,
  currentQuestion: null,
  currentAnswer: null,
  loading: false,
  error: null,

  setQaItems: (qaItems) => set({ qaItems }),
  appendQaItems: (items) => set((state) => ({ qaItems: [...state.qaItems, ...items] })),
  setQaResponse: (qaResponse) => set({ qaResponse }),
  setCurrentQuestion: (currentQuestion) => set({ currentQuestion }),
  setCurrentAnswer: (currentAnswer) => set({ currentAnswer }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  reset: () =>
    set({
      qaItems: [],
      qaResponse: null,
      currentQuestion: null,
      currentAnswer: null,
      loading: false,
      error: null,
    }),
}))
