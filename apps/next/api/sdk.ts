import { client } from './client'
import type {
  DatasetResponse,
  DatasetGenerationRequest,
  DatasetGenerationResponse,
  SimilarityAnalysisResponse,
  CleanSimilarityResponse,
  DeleteDatasetResponse,
  QaListResponse,
  ErrorResponse,
} from './types'

// Helper to extract error message from response
function getErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'detail' in error) {
    return (error as ErrorResponse).detail || fallback
  }
  return fallback
}

// Dataset endpoints

export async function getDatasets(): Promise<DatasetResponse[]> {
  const response = await client.get<DatasetResponse | DatasetResponse[]>({
    url: '/dataset',
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch datasets'))
  }
  const data = response.data as DatasetResponse | DatasetResponse[] | undefined
  return Array.isArray(data) ? data : data ? [data] : []
}

export async function generateDataset(
  body: DatasetGenerationRequest
): Promise<DatasetGenerationResponse> {
  const response = await client.post<DatasetGenerationResponse>({
    url: '/dataset/generate',
    body,
    headers: {
      'Content-Type': 'application/json',
    },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to generate dataset'))
  }
  return response.data as unknown as DatasetGenerationResponse
}

export async function deleteDataset(datasetId: string): Promise<DeleteDatasetResponse> {
  const response = await client.delete<DeleteDatasetResponse>({
    url: `/dataset/${datasetId}`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to delete dataset'))
  }
  return response.data as unknown as DeleteDatasetResponse
}

export async function analyzeSimilarities(
  datasetId: string,
  threshold?: number
): Promise<SimilarityAnalysisResponse> {
  const url = threshold
    ? `/dataset/${datasetId}/analyze-similarities?threshold=${threshold}`
    : `/dataset/${datasetId}/analyze-similarities`

  const response = await client.get<SimilarityAnalysisResponse>({
    url,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to analyze similarities'))
  }
  return response.data as unknown as SimilarityAnalysisResponse
}

export async function cleanSimilarities(
  datasetId: string,
  threshold?: number
): Promise<CleanSimilarityResponse> {
  const url = threshold
    ? `/dataset/${datasetId}/clean-similarities?threshold=${threshold}`
    : `/dataset/${datasetId}/clean-similarities`

  const response = await client.post<CleanSimilarityResponse>({
    url,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to clean similarities'))
  }
  return response.data as unknown as CleanSimilarityResponse
}

// Q&A endpoints

export async function getQAByDataset(
  datasetId: string,
  options?: { limit?: number; offset?: number }
): Promise<QaListResponse> {
  const params = new URLSearchParams()
  if (options?.limit) params.set('limit', String(options.limit))
  if (options?.offset) params.set('offset', String(options.offset))

  const queryString = params.toString()
  const url = queryString ? `/q_a/${datasetId}?${queryString}` : `/q_a/${datasetId}`

  const response = await client.get<QaListResponse>({
    url,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch Q&A data'))
  }
  return response.data as unknown as QaListResponse
}

// Langfuse endpoints

export async function exportToLangfuse(
  datasetName: string,
  langfuseDatasetName?: string | null
): Promise<unknown> {
  const params = new URLSearchParams()
  params.set('dataset_name', datasetName)
  if (langfuseDatasetName) params.set('langfuse_dataset_name', langfuseDatasetName)

  const response = await client.post<unknown>({
    url: `/langfuse/export?${params.toString()}`,
  })
  if (response.error) {
    throw new Error('Failed to export to Langfuse')
  }
  return response.data
}
