import { ref } from 'vue'
import { defineStore } from 'pinia'
import api from '@/composables/useAxios'
import type { 
  Dataset, 
  CleaningResult, 
  DatasetState, 
  AnalyzingResult 
} from '@/types/dataset'

export const useDatasetStore = defineStore('dataset', () => {
  const state = ref<DatasetState>({
    datasets: [],
    dataset: null,
    analyzingResult: null,
    cleaningResult: null,
    loading: false,
    error: null,
  })

  const setLoading = (isLoading: boolean) => {
    state.value.loading = isLoading
  }

  const setError = (err: string | null) => {
    state.value.error = err
  }

  const fetchDatasets = async (): Promise<Dataset[]> => {
    setLoading(true)
    try {
      const response = await api.get(`/dataset`)
      console.log('fetchDatasets response:', response)

      datasets.value = response.data

      return  response.data
    } catch (error) {
      console.error(error)
      setError('Error fetching datasets')
      return []
    } finally {
      setLoading(false)
    }
  }

  const selectDataset = async (datasetId: string): Promise<void> => {
    const foundDataset = datasets.value.find((d) => d.id === datasetId)

    if (!foundDataset) {
      if (datasets.value.length === 0) {
        await fetchDatasets()
        const foundDataset = datasets.value.find((d) => d.id === datasetId)
        if (!foundDataset) {
          throw new Error('Dataset not found')
        }
        dataset.value = foundDataset
      } else {
        throw new Error('Dataset not found')
      }
    } else {
      dataset.value = foundDataset
    }
  }

  const deleteDataset = async (datasetId: string): Promise<void> => {
    setLoading(true)
    try {
      const response = await api.delete(`/dataset/${datasetId}`)

      console.log('deleteDataset response:', response)

      datasets.value = datasets.value.filter((d) => d.id !== datasetId)

      if (dataset.value?.id === datasetId) {
        dataset.value = null
      }
    } catch (error) {
      console.error(error)
      setError('Erreur lors de la suppression du dataset')
      throw error
    } finally {
      setLoading(false)
    }
  }

  const cleanDataset = async (datasetId: string): Promise<CleaningResult | null> => {
    setLoading(true)
    try {
      const response = await api.post(`/dataset/${datasetId}/clean-similarities`)
      state.value.cleaningResult = response.data
      return response.data
    } catch (error) {
      console.error(error)
      setError('Error cleaning dataset')
      return null
    } finally {
      setLoading(false)
    }
  }

  const analyzeDataset = async (datasetId: string): Promise<AnalyzingResult | null> => {
    setLoading(true)
    try {
      const response = await api.get(`/dataset/${datasetId}/analyze-similarities`)
      state.value.analyzingResult = response.data
      return response.data
    } catch (error) {
      console.error(error)
      setError('Error fetching datasets')
      return null
    } finally {
      setLoading(false)
    }
  }

  return {
    state,

    fetchDatasets,
    selectDataset,
    deleteDataset,
    analyzeDataset,
    cleanDataset,
  }
})
