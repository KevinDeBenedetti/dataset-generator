import type { QAResponse } from '@/types/globals'

export interface QAItem {
  id: string
  question: string
  answer: string
  context: string
  source_url: string
  confidence: number
  created_at: string
  metadata: {
    [key: string]: QAResponse
  }
}

export interface QAResponse {
  dataset_name: string
  dataset_id: string
  total_count: number
  returned_count: number
  offset: number
  limit: number
  qa_data: QAItem[]
}

export interface QAState {
  isLoading: boolean
  error: string | null
  datasetId: string | null
  datasetName: string | null
  totalCount: number
  returnedCount: number
  offset: number
  limit: number
}
