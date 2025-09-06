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
  similarities: any[]
}

export interface DatasetState {
    datasets: Dataset[]
    dataset: Dataset | null
    analyzingResult: CleaningResult | null
    cleaningResult: CleaningResult | null
    loading: boolean
    error: string | null
}