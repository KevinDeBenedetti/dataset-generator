import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { DatasetResponse, CleanSimilarityResponse, SimilarityAnalysisResponse } from '@/api'
import {
  getdataset,
  deletedatasetBydataset_idBy,
  getdatasetBydataset_idByanalyze_similarities,
  postdatasetBydataset_idByclean_similarities,
} from '@/api'

export const useDatasetStore = defineStore('dataset', () => {
  const datasets = ref<DatasetResponse[]>([])
  const dataset = ref<DatasetResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const analyzingResult = ref<SimilarityAnalysisResponse | null>(null)
  const cleaningResult = ref<CleanSimilarityResponse | null>(null)

  const analyzeStatus = ref<'idle' | 'pending' | 'success' | 'error'>('idle')
  const cleanStatus = ref<'idle' | 'pending' | 'success' | 'error'>('idle')

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
      error.value = 'Error fetching datasets' + err
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
      await deletedatasetBydataset_idBy({ path: { dataset_id: datasetId } })
      datasets.value = datasets.value.filter((d) => d.id !== datasetId)

      if (dataset.value?.id === datasetId) {
        dataset.value = null
      }
    } catch (err) {
      error.value = 'Error deleting dataset' + err
      throw err
    } finally {
      loading.value = false
    }
  }

  const cleanDataset = async (datasetId: string): Promise<CleanSimilarityResponse | null> => {
    loading.value = true
    error.value = null
    cleanStatus.value = 'pending'
    try {
      const response = await postdatasetBydataset_idByclean_similarities({
        path: { dataset_id: datasetId },
      })
      cleaningResult.value = response.data ?? null
      cleanStatus.value = 'success'
      return cleaningResult.value
    } catch (err) {
      error.value = 'Error cleaning dataset' + err
      cleanStatus.value = 'error'
      return null
    } finally {
      loading.value = false
    }
  }

  const analyzeDataset = async (datasetId: string): Promise<SimilarityAnalysisResponse | null> => {
    loading.value = true
    error.value = null
    analyzeStatus.value = 'pending'
    try {
      const response = await getdatasetBydataset_idByanalyze_similarities({
        path: { dataset_id: datasetId },
      })
      analyzingResult.value = response.data ?? null
      analyzeStatus.value = 'success'
      return analyzingResult.value
    } catch (err) {
      error.value = 'Error analyzing dataset' + err
      analyzeStatus.value = 'error'
      return null
    } finally {
      loading.value = false
    }
  }

  const resetStatus = () => {
    analyzeStatus.value = 'idle'
    cleanStatus.value = 'idle'
    error.value = null
    dataset.value = null
  }

  return {
    datasets,
    dataset,
    loading,
    error,
    analyzingResult,
    cleaningResult,
    cleanStatus,
    analyzeStatus,

    fetchDatasets,
    selectDataset,
    deleteDataset,
    analyzeDataset,
    cleanDataset,
    resetStatus,
  }
})
