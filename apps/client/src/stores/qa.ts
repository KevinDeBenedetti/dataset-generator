import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

import type { QAItem, QAResponse, QAState } from '@/types/qa'

export const useQAStore = defineStore('qa', () => {
  // États réactifs
  const qaItems = ref<QAItem[]>([])
  const currentQuestion = ref<string | null>(null)
  const currentAnswer = ref<string | null>(null)
  const state = ref<QAState>({
    isLoading: false,
    error: null,
    datasetId: null,
    datasetName: null,
    totalCount: 0,
    returnedCount: 0,
    offset: 0,
    limit: 10,
  })

  // Computed properties
  const questions = computed(() => qaItems.value.map((item) => item.question))
  const answers = computed(() => qaItems.value.map((item) => item.answer))
  const hasData = computed(() => qaItems.value.length > 0)
  const isError = computed(() => state.value.error !== null)
  const hasMoreData = computed(
    () => state.value.offset + state.value.returnedCount < state.value.totalCount,
  )

  // Actions
  const clearError = () => {
    state.value.error = null
  }

  const setLoading = (loading: boolean) => {
    state.value.isLoading = loading
  }

  const setError = (error: string | null) => {
    state.value.error = error
  }

  const clearData = () => {
    qaItems.value = []
    currentQuestion.value = null
    currentAnswer.value = null
    state.value = {
      ...state.value,
      datasetId: null,
      datasetName: null,
      totalCount: 0,
      returnedCount: 0,
      offset: 0,
    }
  }

  const fetchQAByDataset = async (
    datasetId: string,
    options?: { limit?: number; offset?: number },
  ) => {
    try {
      setLoading(true)
      clearError()

      const { limit = 10, offset = 0 } = options || {}
      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
      const url = new URL(`${apiBaseUrl}/q_a/${datasetId}`)
      url.searchParams.set('limit', limit.toString())
      url.searchParams.set('offset', offset.toString())

      const response = await fetch(url.toString(), {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        throw new Error(errorData?.message || `Erreur ${response.status}: ${response.statusText}`)
      }

      const data: QAResponse = await response.json()

      // Si offset = 0, on remplace les données, sinon on les ajoute (pagination)
      if (offset === 0) {
        qaItems.value = data.qa_data || []
      } else {
        qaItems.value.push(...(data.qa_data || []))
      }

      state.value = {
        ...state.value,
        datasetId: data.dataset_id,
        datasetName: data.dataset_name,
        totalCount: data.total_count,
        returnedCount: data.returned_count,
        offset: data.offset,
        limit: data.limit,
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Erreur inconnue'
      setError(errorMessage)
      console.error('Failed to fetch QA:', error)
      throw error
    } finally {
      setLoading(false)
    }
  }

  const loadMoreQA = async () => {
    if (!state.value.datasetId || !hasMoreData.value || state.value.isLoading) {
      return
    }

    const nextOffset = state.value.offset + state.value.returnedCount
    await fetchQAByDataset(state.value.datasetId, {
      limit: state.value.limit,
      offset: nextOffset,
    })
  }

  return {
    // États
    qaItems,
    currentQuestion,
    currentAnswer,
    state,

    // Computed
    questions,
    answers,
    hasData,
    isError,
    hasMoreData,

    // Actions
    fetchQAByDataset,
    loadMoreQA,
    clearError,
    clearData,
    setLoading,
    setError,
  }
})
