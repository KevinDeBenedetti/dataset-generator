import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ExportDatasetLangfuseExportPostData } from '@/api'
import { postlangfuseexport } from '@/api'

export const useLangfuseStore = defineStore('langfuse', () => {
  const loading = ref(false)
  const error = ref<string | null>(null)

  const exportToLangfuse = async (datasetName: string, langfuseDatasetName?: string | null) => {
    loading.value = true
    error.value = null

    try {
      const payload: ExportDatasetLangfuseExportPostData = {
        url: '/langfuse/export',
        query: {
          dataset_name: datasetName,
          langfuse_dataset_name: langfuseDatasetName ?? undefined,
        },
      }

      const response = await postlangfuseexport(payload)
      return response.data
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Export failed'
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    error,

    exportToLangfuse,
  }
})
