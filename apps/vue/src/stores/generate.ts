import { ref } from 'vue'
import { defineStore } from 'pinia'

import type { DatasetResponse, DatasetGenerationResponse } from '@/api'
import { postdatasetgenerate } from '@/api'

interface GenerateOptions {
  targetLanguage: string | null
  similarityThreshold: number
}

export const useGenerateStore = defineStore('generate', () => {
  const dataset = ref<DatasetResponse | DatasetGenerationResponse | null>(null)
  const generationStatus = ref<'idle' | 'pending' | 'success' | 'error'>('idle')

  const error = ref<string | null>(null)

  const generateDataset = async (
    url: string,
    name: string,
    options: GenerateOptions
  ): Promise<DatasetResponse | DatasetGenerationResponse | null> => {
    generationStatus.value = 'pending'
    error.value = null

    try {
      const response = await postdatasetgenerate({
        body: {
          url,
          dataset_name: name,
          target_language: options.targetLanguage,
          similarity_threshold: options.similarityThreshold,
        },
      })

      dataset.value = response.data ?? null
      generationStatus.value = 'success'
      return response.data ?? null
    } catch (err) {
      console.error('Error generating dataset:', err)
      generationStatus.value = 'error'
      error.value = 'Failed to generate dataset'
      return null
    }
  }

  const resetStatus = () => {
    generationStatus.value = 'idle'
    error.value = null
    dataset.value = null
  }

  return {
    dataset,
    generationStatus,

    error,
    generateDataset,
    resetStatus,
  }
})
