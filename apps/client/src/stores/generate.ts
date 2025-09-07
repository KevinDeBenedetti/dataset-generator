import { ref } from 'vue'
import { defineStore } from 'pinia'
import api from '@/composables/useAxios'
import { useDatasetStore } from '@/stores/dataset'
import type { GeneratedDataset, ProcessStatus, DatasetGenerationRequest } from '@/types/dataset'

export const useGenerateStore = defineStore('generate', () => {
  const datasetStore = useDatasetStore()

  const dataset = ref<GeneratedDataset | null>(null)
  const generationStatus = ref<ProcessStatus>('idle')
  const analyzeStatus = ref<ProcessStatus>('idle')
  const cleanStatus = ref<ProcessStatus>('idle')
  const errorMessage = ref<string | null>(null)

  const state = ref({
    loading: false,
    error: null,
  })

  const setLoading = (isLoading: boolean) => {
    state.value.loading = isLoading
  }

  const setError = (err: string | null) => {
    errorMessage.value = err
  }

  const generateDataset = async (
    url: string,
    datasetName: string,
    options: {
      modelCleaning?: string | null
      targetLanguage?: string | null
      modelQa?: string | null
      similarityThreshold?: number
    } = {},
  ): Promise<GeneratedDataset | null> => {
    try {
      generationStatus.value = 'pending'
      setLoading(true)

      const requestBody: DatasetGenerationRequest = {
        url,
        dataset_name: datasetName,
        model_cleaning: options.modelCleaning || null,
        target_language: options.targetLanguage || null,
        model_qa: options.modelQa || null,
        similarity_threshold:
          options.similarityThreshold !== undefined ? options.similarityThreshold : 0.9,
      }

      const response = await api.post('/generate/dataset/url', requestBody)

      dataset.value = response.data
      generationStatus.value = 'success'

      // Actualiser la liste des datasets
      await datasetStore.fetchDatasets()

      return response.data
    } catch (error) {
      console.error(error)
      setError('Error generating dataset')
      generationStatus.value = 'error'
      return null
    } finally {
      setLoading(false)
    }
  }

  const analyzeDataset = async (): Promise<any> => {
    if (!dataset.value) return null

    try {
      analyzeStatus.value = 'pending'
      const datasetId = datasetStore.state.datasets.find(
        (d) => d.name === dataset.value?.dataset_name,
      )?.id

      if (!datasetId) {
        throw new Error('Dataset not found')
      }

      const result = await datasetStore.analyzeDataset(datasetId)
      analyzeStatus.value = 'success'
      return result
    } catch (error) {
      console.error(error)
      setError('Error analyzing dataset')
      analyzeStatus.value = 'error'
      return null
    }
  }

  const cleanDataset = async (): Promise<any> => {
    if (!dataset.value) return null

    try {
      cleanStatus.value = 'pending'
      const datasetId = datasetStore.state.datasets.find(
        (d) => d.name === dataset.value?.dataset_name,
      )?.id

      if (!datasetId) {
        throw new Error('Dataset not found')
      }

      const result = await datasetStore.cleanDataset(datasetId)
      cleanStatus.value = 'success'
      return result
    } catch (error) {
      console.error(error)
      setError('Error cleaning dataset')
      cleanStatus.value = 'error'
      return null
    }
  }

  return {
    state,
    dataset,
    generationStatus,
    analyzeStatus,
    cleanStatus,
    errorMessage,
    generateDataset,
    analyzeDataset,
    cleanDataset,
  }
})
