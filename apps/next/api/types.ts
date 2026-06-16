// Temporary types until API generation is set up
// These match the FastAPI backend schema

export type CleanSimilarityPair = {
  keep_id: string
  remove_id: string
  similarity: number
  keep_question: string
  remove_question: string
}

export type CleanSimilarityResponse = {
  dataset_id: string
  dataset_name: string
  threshold: number
  total_records: number
  removed_records: number
  details: Array<CleanSimilarityPair>
  removed_items: Array<RemovedRecord>
}

export type DatasetGenerationRequest = {
  url: string
  dataset_name: string
  model_cleaning?: string | null
  target_language?: string | null
  model_qa?: string | null
  similarity_threshold?: number
  /** Explore the whole site (follow same-domain internal links) instead of the seed URL only */
  crawl?: boolean
  /** Max link-following depth when crawling (defaults to backend config) */
  max_depth?: number | null
  /** Max number of pages to crawl (defaults to backend config) */
  max_pages?: number | null
  /** Create/version the dataset in Langfuse at generation time */
  sync_langfuse?: boolean
}

export type LangfuseSyncSummary = {
  dataset_name: string
  version: number
  run_name: string
  total_items: number
  created_count: number
  failed_count: number
}

export type AgentQaPair = {
  question: string
  answer: string
  context: string
  confidence?: number | null
}

export type QaAgentTestRequest = {
  text: string
  target_language?: string | null
  model?: string | null
}

export type QaAgentTestResponse = {
  ok: boolean
  model: string
  target_language: string
  count: number
  raw_length: number
  raw_response: string
  qa_pairs: Array<AgentQaPair>
  error?: string | null
}

export type PipelineStepStatus = 'success' | 'warning' | 'error'

export type PipelineStep = {
  key: string
  label: string
  status: PipelineStepStatus
  duration_ms: number
  detail: string
}

export type DatasetGenerationResponse = {
  id: string
  qa_pairs: Array<QaPair>
  dataset_name: string
  model_cleaning: string
  target_language: string
  model_qa: string
  similarity_threshold: number
  total_questions: number
  pages_crawled?: number
  processing_time: number
  steps?: Array<PipelineStep>
  scraped_content?: string | null
  langfuse?: LangfuseSyncSummary | null
}

export type DatasetResponse = {
  id: string
  name: string
  description?: string | null
  qa_sources_count?: number | null
  created_at?: string | null
  message?: string | null
}

export type DeleteDatasetResponse = {
  message: string
  dataset_id: string
  records_deleted: number
}

export type ErrorResponse = {
  detail: string
  error_code?: string | null
}

export type HttpValidationError = {
  detail?: Array<ValidationError>
}

export type QaItem = {
  id: string
  question: string
  answer: string
  context: string
  source_url?: string | null
  confidence?: number
  created_at: string
  metadata?: {
    [key: string]: unknown
  } | null
}

export type QaListResponse = {
  dataset_name: string
  dataset_id: string
  total_count: number
  returned_count: number
  offset?: number
  limit?: number | null
  qa_data: Array<QaItem>
}

export type QaPair = {
  question: string
  answer: string
}

export type QaResponse = {
  id: string
  question: string
  answer: string
  context: string
  source_url?: string | null
  confidence?: number
  created_at: string
  updated_at?: string | null
  metadata?: {
    [key: string]: unknown
  } | null
  dataset?: {
    [key: string]: string | null
  } | null
}

export type RemovedRecord = {
  id: string
  question: string
  similarity: number
  kept_id: string
}

export type SimilarityAnalysisResponse = {
  dataset_id: string
  dataset_name: string
  threshold: number
  total_records: number
  similar_pairs_found: number
  similarities: Array<SimilarityPair>
}

export type SimilarityPair = {
  record1_id: string
  record2_id: string
  similarity: number
  question1: string
  question2: string
}

export type ValidationError = {
  loc: Array<string | number>
  msg: string
  type: string
}
