import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/composables/useAxios'

export const useLangfuseStore = defineStore('langfuse', () => {
  const isExporting = ref(false)
  const error = ref<string | null>(null)

  const setError = (err: string | null) => {
    error.value = err
  }

  const exportToLangfuse = async (datasetName: string, langfuseDatasetName?: string) => {
    isExporting.value = true
    error.value = null

    try {
      const params = new URLSearchParams({
        dataset_name: datasetName,
      })

      if (langfuseDatasetName) {
        params.append('langfuse_dataset_name', langfuseDatasetName)
      }

      const response = await api.post(`/langfuse/export?${params}`)
      console.log('Response :', response.data)
      return response.data
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Export failed'
      setError(errorMessage)
      throw err
    } finally {
      isExporting.value = false
    }
  }

  return {
    isExporting,
    error,
    setError,
    exportToLangfuse,
  }
})
