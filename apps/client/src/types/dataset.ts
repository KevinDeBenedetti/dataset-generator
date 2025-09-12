import type { DatasetRecord } from '@/types/globals'

export interface Dataset {
  id: string
  name: string
  url?: string
  created_at: string
  updated_at: string
  file_count?: number
  total_size?: number
  description?: string
}

export interface SimilarRecord {
  record_id: string
  question?: string
}

export interface Similarity {
  records: SimilarRecord[]
  similarity: number
}

export interface AnalyzingResult {
  dataset_id: string
  dataset_name: string
  threshold: number
  total_records: number
  similar_pairs_found: number
  similarities: Similarity[]
}

export interface CleaningResult {
  dataset_id: string
  dataset_name: string
  threshold: number
  total_records: number
  similar_pairs_found: number
  similarities: DatasetRecord[]
}

export interface DatasetState {
  datasets: Dataset[]
  dataset: Dataset | null
  analyzingResult: CleaningResult | null
  cleaningResult: CleaningResult | null
  loading: boolean
  error: string | null
}

export interface QAPair {
  question: string
  answer: string
}

export interface GeneratedDataset {
  id: string // Ajout de l'ID du dataset
  qa_pairs: QAPair[]
  dataset_name: string
  model_cleaning: string
  target_language: string
  model_qa: string
  similarity_threshold: number
  total_questions: number
  processing_time: number
}

export type ProcessStatus = 'idle' | 'pending' | 'success' | 'error'

export interface DatasetGenerationRequest {
  url: string
  dataset_name: string
  model_cleaning: string | null
  target_language: string | null
  model_qa: string | null
  similarity_threshold: number
}
