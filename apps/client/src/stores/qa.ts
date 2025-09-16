import { ref } from 'vue'
import { defineStore } from 'pinia'

import type { QaItem, QaListResponse } from '@/api'
import { getq_aBydataset_idBy } from '@/api/sdk.gen'

export const useQAStore = defineStore('qa', () => {
  const qaItems = ref<QaItem[]>([])
  const qaResponse = ref<QaListResponse | null>(null)

  const currentQuestion = ref<string | null>(null)
  const currentAnswer = ref<string | null>(null)

  const loading = ref(false)
  const error = ref<string | null>(null)

  const fetchQAByDataset = async (
    datasetId: string,
    options?: { limit?: number; offset?: number; replace?: boolean }
  ) => {
    try {
      loading.value = true
      error.value = null

      const { limit = 10, offset = 0, replace = true } = options || {}

      const response = await getq_aBydataset_idBy({
        path: { dataset_id: datasetId },
        query: { limit, offset },
      })

      const data = response.data as QaListResponse

      if (replace) {
        qaItems.value = data.qa_data || []
      } else {
        qaItems.value.push(...(data.qa_data || []))
      }

      qaResponse.value = data

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Erreur inconnue'
      error.value = errorMessage
      console.error('Failed to fetch QA:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  const loadMoreQA = async () => {
    if (!qaResponse.value?.dataset_id || loading.value) {
      return
    }

    const nextOffset = (qaResponse.value?.offset ?? 0) + (qaResponse.value?.returned_count ?? 0)
    await fetchQAByDataset(qaResponse.value!.dataset_id, {
      limit: qaResponse.value?.limit ?? 10,
      offset: nextOffset,
      replace: false, // Pour "load more", on ajoute les données
    })
  }

  const goToPage = async (page: number) => {
    if (!qaResponse.value?.dataset_id || loading.value) {
      return
    }

    const limit = qaResponse.value?.limit ?? 10
    const offset = (page - 1) * limit
    await fetchQAByDataset(qaResponse.value!.dataset_id, {
      limit: limit,
      offset: offset,
      replace: true, // Pour la pagination, on remplace les données
    })
  }

  return {
    qaItems,
    currentQuestion,
    currentAnswer,
    qaResponse,

    fetchQAByDataset,
    loadMoreQA,
    goToPage,
  }
})
