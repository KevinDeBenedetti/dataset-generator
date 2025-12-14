import { create } from 'zustand'

interface LangfuseState {
  loading: boolean
  error: string | null

  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  reset: () => void
}

export const useLangfuseStore = create<LangfuseState>((set) => ({
  loading: false,
  error: null,

  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  reset: () => set({ loading: false, error: null }),
}))
