import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

import api from '@/composables/useAxios'

import type { QAItem, QAResponse, QAState } from '@/types/qa'

export const useQAStore = defineStore('qa', () => {
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

  const questions = computed(() => qaItems.value.map((item) => item.question))
  const answers = computed(() => qaItems.value.map((item) => item.answer))
  const hasData = computed(() => qaItems.value.length > 0)
  const isError = computed(() => state.value.error !== null)
  const hasMoreData = computed(
    () => state.value.offset + state.value.returnedCount < state.value.totalCount,
  )

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
    options?: { limit?: number; offset?: number; replace?: boolean },
  ) => {
    try {
      setLoading(true)
      clearError()

      const { limit = 10, offset = 0, replace = true } = options || {}
      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
      const url = new URL(`${apiBaseUrl}/q_a/${datasetId}`)
      url.searchParams.set('limit', limit.toString())
      url.searchParams.set('offset', offset.toString())

      const response = await api.get(url.toString())

      const data: QAResponse = response.data

      // Pour la pagination, on remplace toujours les données
      // Pour le "load more", on ajoute les données
      if (replace) {
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
      replace: false, // Pour "load more", on ajoute les données
    })
  }

  const goToPage = async (page: number) => {
    if (!state.value.datasetId || state.value.isLoading) {
      return
    }

    const offset = (page - 1) * state.value.limit
    await fetchQAByDataset(state.value.datasetId, {
      limit: state.value.limit,
      offset: offset,
      replace: true, // Pour la pagination, on remplace les données
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
    goToPage,
    clearError,
    clearData,
    setLoading,
    setError,
  }
})
