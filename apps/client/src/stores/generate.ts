import { ref } from 'vue'
import { defineStore } from 'pinia'
import api from '@/composables/useAxios'
import type { Dataset, CleaningResult, AnalyzingResult } from '@/types/dataset'

interface GenerateOptions {
  targetLanguage: string | null
  similarityThreshold: number
}

export const useGenerateStore = defineStore('generate', () => {
  const dataset = ref<Dataset | null>(null)
  const generationStatus = ref<'idle' | 'pending' | 'success' | 'error'>('idle')
  const analyzeStatus = ref<'idle' | 'pending' | 'success' | 'error'>('idle')
  const cleanStatus = ref<'idle' | 'pending' | 'success' | 'error'>('idle')
  const errorMessage = ref<string | null>(null)

  const generateDataset = async (
    url: string,
    name: string,
    options: GenerateOptions,
  ): Promise<Dataset | null> => {
    generationStatus.value = 'pending'
    errorMessage.value = null

    try {
      const response = await api.post('/dataset/generate', {
        url,
        name,
        target_language: options.targetLanguage,
        similarity_threshold: options.similarityThreshold,
      })

      dataset.value = response.data
      generationStatus.value = 'success'
      return response.data
    } catch (error) {
      console.error('Error generating dataset:', error)
      generationStatus.value = 'error'
      errorMessage.value = 'Failed to generate dataset'
      return null
    }
  }

  const analyzeDataset = async (): Promise<AnalyzingResult | null> => {
    if (!dataset.value) {
      errorMessage.value = 'No dataset available to analyze'
      return null
    }

    analyzeStatus.value = 'pending'
    errorMessage.value = null

    try {
      const response = await api.get(`/dataset/${dataset.value.id}/analyze-similarities`)
      analyzeStatus.value = 'success'
      return response.data
    } catch (error) {
      console.error('Error analyzing dataset:', error)
      analyzeStatus.value = 'error'
      errorMessage.value = 'Failed to analyze dataset'
      return null
    }
  }

  const cleanDataset = async (): Promise<CleaningResult | null> => {
    if (!dataset.value) {
      errorMessage.value = 'No dataset available to clean'
      return null
    }

    cleanStatus.value = 'pending'
    errorMessage.value = null

    try {
      const response = await api.post(`/dataset/${dataset.value.id}/clean-similarities`)
      cleanStatus.value = 'success'
      return response.data
    } catch (error: unknown) {
      console.error('Error cleaning dataset:', error)
      cleanStatus.value = 'error'
      errorMessage.value = 'Failed to clean dataset'
      return null
    }
  }

  const resetStatus = () => {
    generationStatus.value = 'idle'
    analyzeStatus.value = 'idle'
    cleanStatus.value = 'idle'
    errorMessage.value = null
    dataset.value = null
  }

  return {
    dataset,
    generationStatus,
    analyzeStatus,
    cleanStatus,
    errorMessage,
    generateDataset,
    analyzeDataset,
    cleanDataset,
    resetStatus,
  }
})
