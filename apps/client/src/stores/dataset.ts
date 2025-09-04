import { ref } from 'vue'
import { defineStore } from 'pinia'

export type GenerationStatus = 'idle' | 'pending' | 'success' | 'error'
export type AnalyzeStatus = 'idle' | 'pending' | 'success' | 'error'
export type CleanStatus = 'idle' | 'pending' | 'success' | 'error'

export const useDatasetStore = defineStore('dataset', () => {
  const generationStatus = ref<GenerationStatus>('idle')
  const analyzeStatus = ref<AnalyzeStatus>('idle')
  const cleanStatus = ref<CleanStatus>('idle')
  const errorMessage = ref<string>('')
  const lastResult = ref<any>(null)
  const analyzeResult = ref<any>(null)
  const cleanResult = ref<any>(null)
  const currentDatasetName = ref<string>('')
  const datasets = ref<any[]>([])
  const loading = ref<boolean>(false)
  const error = ref<string | null>(null)

  const generateDataset = async (url: string, datasetName: string) => {
    generationStatus.value = 'pending'
    errorMessage.value = ''
    currentDatasetName.value = datasetName

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

  const analyzeDataset = async (datasetName?: string) => {
    const nameToUse = datasetName || currentDatasetName.value
    if (!nameToUse) {
      throw new Error('Aucun nom de dataset fourni')
    }

    analyzeStatus.value = 'pending'
    errorMessage.value = ''

    try {
      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
      const response = await fetch(`${apiBaseUrl}/dataset/${nameToUse}/analyze-similarities`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        throw new Error(errorData?.message || `Erreur ${response.status}: ${response.statusText}`)
      }

      const data = await response.json()
      analyzeStatus.value = 'success'
      analyzeResult.value = data
      console.log(data)
      return data
    } catch (error) {
      analyzeStatus.value = 'error'
      errorMessage.value =
        error instanceof Error ? error.message : 'Une erreur inconnue est survenue'
      throw error
    }
  }

  const cleanDataset = async (datasetName?: string) => {
    const nameToUse = datasetName || currentDatasetName.value
    if (!nameToUse) {
      throw new Error('Aucun nom de dataset fourni')
    }

    cleanStatus.value = 'pending'
    errorMessage.value = ''

    try {
      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
      const response = await fetch(`${apiBaseUrl}/dataset/${nameToUse}/clean-similarities`, {
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
      cleanStatus.value = 'success'
      cleanResult.value = data
      console.log(data)
      return data
    } catch (error) {
      cleanStatus.value = 'error'
      errorMessage.value =
        error instanceof Error ? error.message : 'Une erreur inconnue est survenue'
      throw error
    }
  }

  const fetchDatasets = async () => {
    try {
      loading.value = true
      error.value = null

      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
      const response = await fetch(`${apiBaseUrl}/dataset`)
      if (!response.ok) {
        throw new Error(`Erreur ${response.status}: ${response.statusText}`)
      }

      const data = await response.json()
      datasets.value = data

      console.log("Données reçues de l'API:", data)
      return data
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Erreur inconnue'
      console.error('Erreur lors de la récupération des datasets:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  const deleteDataset = async (datasetId: string) => {
    try {
      loading.value = true
      error.value = null

      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
      const response = await fetch(`${apiBaseUrl}/dataset/${datasetId}`, {
        method: 'DELETE',
      })

      if (!response.ok) {
        throw new Error(`Erreur ${response.status}: ${response.statusText}`)
      }

      // Retirer le dataset de la liste locale
      datasets.value = datasets.value.filter((dataset) => dataset.id !== datasetId)

      console.log('Dataset supprimé:', datasetId)
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Erreur lors de la suppression'
      console.error('Erreur lors de la suppression du dataset:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  const resetStatus = () => {
    generationStatus.value = 'idle'
    analyzeStatus.value = 'idle'
    cleanStatus.value = 'idle'
    errorMessage.value = ''
    lastResult.value = null
    analyzeResult.value = null
    cleanResult.value = null
    currentDatasetName.value = ''
  }

  return {
    generationStatus,
    analyzeStatus,
    cleanStatus,
    errorMessage,
    lastResult,
    analyzeResult,
    cleanResult,
    currentDatasetName,
    datasets,
    loading,
    error,
    generateDataset,
    analyzeDataset,
    cleanDataset,
    fetchDatasets,
    deleteDataset,
    resetStatus,
  }
})
