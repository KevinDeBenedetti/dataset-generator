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

      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
      const response = await fetch(`${apiBaseUrl}/generate/dataset/url?${params}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        throw new Error(errorData?.message || `Erreur ${response.status}: ${response.statusText}`)
      }

      const data = await response.json()
      generationStatus.value = 'success'
      lastResult.value = data
      console.log(data)
      return data
    } catch (error) {
      generationStatus.value = 'error'
      errorMessage.value =
        error instanceof Error ? error.message : 'Une erreur inconnue est survenue'
      throw error
    }
  }

  async function cleanDataset() {
    generationStatus.value = 'pending'
    errorMessage.value = ''

    try {
      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
      const response = await fetch(`${apiBaseUrl}/clean/dataset`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        throw new Error(errorData?.message || `Erreur ${response.status}: ${response.statusText}`)
      }

      const data = await response.json()
      generationStatus.value = 'success'
      lastResult.value = data
      console.log(data)
      return data
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
