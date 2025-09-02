import { ref } from 'vue'
import { defineStore } from 'pinia'

export type GenerationStatus = 'idle' | 'pending' | 'success' | 'error'

export const useDatasetStore = defineStore('dataset', () => {
  const generationStatus = ref<GenerationStatus>('idle')
  const errorMessage = ref<string>('')
  const lastResult = ref<any>(null)

  async function generateDataset(url: string, datasetName: string) {
    generationStatus.value = 'pending'
    errorMessage.value = ''

    try {
      const params = new URLSearchParams({
        url: url,
        dataset_name: datasetName,
      })

      const response = await fetch(`http://localhost:8000/generate/dataset/url?${params}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        // body: JSON.stringify({ url })
      })

      console.log(response)
      return
    } catch (error) {
      generationStatus.value = 'error'
      errorMessage.value =
        error instanceof Error ? error.message : 'Une erreur inconnue est survenue'
      throw error
    }
  }

  function resetStatus() {
    generationStatus.value = 'idle'
    errorMessage.value = ''
    lastResult.value = null
  }

  return {
    generationStatus,
    errorMessage,
    lastResult,
    generateDataset,
    resetStatus,
  }
})
