import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useGenerateStore = defineStore('generate', () => {

  const generateDataset = async (params: GenerateDatasetParams): Promise<any> => {
    try {
      setOperationState('generateDataset', 'loading')

      const urlParams = new URLSearchParams({
        url: params.url,
        dataset_name: params.datasetName,
      })

      const response = await fetch(`${getApiBaseUrl()}/generate/dataset/url?${urlParams}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })

      const data = await handleApiResponse(response)
      results.value.generation = data
      setOperationState('generateDataset', 'success')

      // Actualiser la liste des datasets
      await fetchDatasets()

      return data
    } catch (error) {
      const apiError = createApiError(error, 'Erreur lors de la génération du dataset')
      setOperationState('generateDataset', 'error', apiError)
      throw apiError
    }
  }
})