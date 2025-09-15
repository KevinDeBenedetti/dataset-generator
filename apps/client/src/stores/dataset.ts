import { ref } from 'vue'
import { defineStore } from 'pinia'
import type {
  DatasetResponse,
  CleanSimilarityResponse,
  SimilarityAnalysisResponse,
} from '@/api/types.gen'
import {
  getdataset,
  deletedatasetBydataset_idBy,
  getdatasetBydataset_idByanalyze_similarities,
  postdatasetBydataset_idByclean_similarities,
} from '@/api/sdk.gen'

export const useDatasetStore = defineStore('dataset', () => {
  const datasets = ref<DatasetResponse[]>([])
  const dataset = ref<DatasetResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const analyzingResult = ref<SimilarityAnalysisResponse | null>(null)
  const cleaningResult = ref<CleanSimilarityResponse | null>(null)

  const fetchDatasets = async (): Promise<DatasetResponse[]> => {
    loading.value = true
    error.value = null
    try {
      const response = await getdataset()
      const data = Array.isArray(response.data)
        ? response.data
        : response.data
          ? [response.data]
          : []
      datasets.value = data as DatasetResponse[]
      return datasets.value
    } catch (err) {
      console.error(err)
      error.value = 'Error fetching datasets'
      return []
    } finally {
      loading.value = false
    }
  }

  const selectDataset = async (datasetId: string): Promise<void> => {
    let found = datasets.value.find((d) => d.id === datasetId)

    if (!found) {
      if (datasets.value.length === 0) {
        await fetchDatasets()
        found = datasets.value.find((d) => d.id === datasetId)
        if (!found) {
          throw new Error('Dataset not found')
        }
        dataset.value = found
      } else {
        throw new Error('Dataset not found')
      }
    } else {
      dataset.value = found
    }
  }

  const deleteDataset = async (datasetId: string): Promise<void> => {
    loading.value = true
    error.value = null
    try {
      const response = await deletedatasetBydataset_idBy({ path: { dataset_id: datasetId } })
      console.log('deleteDataset response:', response)

      datasets.value = datasets.value.filter((d) => d.id !== datasetId)

      if (dataset.value?.id === datasetId) {
        dataset.value = null
      }
    } catch (err) {
      console.error(err)
      error.value = 'Erreur lors de la suppression du dataset'
      throw err
    } finally {
      loading.value = false
    }
  }

  const cleanDataset = async (datasetId: string): Promise<CleanSimilarityResponse | null> => {
    loading.value = true
    error.value = null
    try {
      const response = await postdatasetBydataset_idByclean_similarities({
        path: { dataset_id: datasetId },
      })
      cleaningResult.value = response.data ?? null
      return cleaningResult.value
    } catch (err) {
      console.error(err)
      error.value = 'Error cleaning dataset'
      return null
    } finally {
      loading.value = false
    }
  }

  const analyzeDataset = async (datasetId: string): Promise<SimilarityAnalysisResponse | null> => {
    loading.value = true
    error.value = null
    try {
      const response = await getdatasetBydataset_idByanalyze_similarities({
        path: { dataset_id: datasetId },
      })
      analyzingResult.value = response.data ?? null
      return analyzingResult.value
    } catch (err) {
      console.error(err)
      error.value = 'Error analyzing dataset'
      return null
    } finally {
      loading.value = false
    }
  }

  return {
    datasets,
    dataset,
    loading,
    error,
    analyzingResult,
    cleaningResult,

    fetchDatasets,
    selectDataset,
    deleteDataset,
    analyzeDataset,
    cleanDataset,
  }
})
