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
    try {
      setLoading(true)
      const response = await api.get(`/dataset`)
      state.value.datasets = response.data
      return response.data
    } catch (error) {
      console.error(error)
      setError('Error fetching datasets')
      return []
    } finally {
      setLoading(false)
    }
  }

  const selectDataset = async (datasetId: string): Promise<void> => {
    const foundDataset = state.value.datasets.find((d) => d.id === datasetId)

    if (!foundDataset) {
      if (state.value.datasets.length === 0) {
        await fetchDatasets()
        const foundDataset = state.value.datasets.find((d) => d.id === datasetId)
        if (!foundDataset) {
          throw new Error('Dataset not found')
        }
        state.value.dataset = foundDataset
      } else {
        throw new Error('Dataset not found')
      }
    } else {
      state.value.dataset = foundDataset
    }
  }

  const deleteDataset = async (datasetId: string): Promise<void> => {
    setLoading(true)
    try {
      const response = await api.delete(`/dataset/${datasetId}`)

      console.log('deleteDataset response:', response)

      state.value.datasets = state.value.datasets.filter((d) => d.id !== datasetId)

      if (state.value.dataset?.id === datasetId) {
        state.value.dataset = null
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
