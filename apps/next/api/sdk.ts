// Hand-written, friendlier wrappers around the auto-generated client.
//
// `@hey-api/openapi-ts` regenerates `sdk.gen.ts`/`types.gen.ts`/`index.ts`, so
// these higher-level helpers (which unwrap responses, flatten errors and add the
// SSE streaming endpoint) live here, in a file the generator never touches.
import { client } from './client.gen'

// The auth cookie is httpOnly and set by the API (cross-origin in dev), so every
// request must send/accept credentials for the session to work.
client.setConfig({ credentials: 'include' })
import type {
  DatasetResponse,
  DatasetGenerationRequest,
  DatasetGenerationResponse,
  SimilarityAnalysisResponse,
  CleanSimilarityResponse,
  DeleteDatasetResponse,
  QaListResponse,
  QaAgentTestRequest,
  QaAgentTestResponse,
  PipelineStep,
  ValidationError,
} from './types.gen'

// Helper to extract a readable error message from an API error body.
// FastAPI returns either { detail: string } (our ErrorResponse) or, on a 422,
// { detail: ValidationError[] }. The array case must be flattened to a string,
// otherwise it surfaces as "[object Object]" in the UI.
function getErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== 'object' || !('detail' in error)) {
    return fallback
  }

  const detail = (error as { detail?: unknown }).detail

  if (typeof detail === 'string') {
    return detail || fallback
  }

  if (Array.isArray(detail)) {
    const messages = (detail as ValidationError[])
      .map((item) => {
        const loc = Array.isArray(item?.loc)
          ? item.loc.filter((part) => part !== 'body').join('.')
          : ''
        const msg = item?.msg ?? ''
        return loc ? `${loc}: ${msg}` : String(msg)
      })
      .filter(Boolean)
    if (messages.length) {
      return messages.join('; ')
    }
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

// SSE event shapes emitted by POST /dataset/generate/stream.
type StreamEvent =
  | { type: 'step'; step: PipelineStep }
  | { type: 'page'; [key: string]: unknown }
  | { type: 'result'; data: DatasetGenerationResponse }
  | { type: 'error'; detail?: unknown }

interface GenerateStreamHandlers {
  onStep?: (step: PipelineStep) => void
  onPage?: (page: Record<string, unknown>) => void
}

// Generate a dataset while streaming pipeline progress over Server-Sent Events.
// Resolves with the final `result` payload; rejects on an `error` event.
export async function generateDatasetStream(
  body: DatasetGenerationRequest,
  handlers: GenerateStreamHandlers = {}
): Promise<DatasetGenerationResponse> {
  const baseUrl = client.getConfig().baseUrl ?? ''
  const response = await fetch(`${baseUrl}/dataset/generate/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok || !response.body) {
    let message = 'Failed to generate dataset'
    try {
      const error = await response.json()
      message = getErrorMessage(error, message)
    } catch {
      // Non-JSON error body — keep the fallback message.
    }
    throw new Error(message)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: DatasetGenerationResponse | null = null

  const handleEvent = (event: StreamEvent) => {
    switch (event.type) {
      case 'step':
        handlers.onStep?.(event.step)
        break
      case 'page':
        handlers.onPage?.(event)
        break
      case 'result':
        result = event.data
        break
      case 'error':
        throw new Error(getErrorMessage(event, 'Failed to generate dataset'))
    }
  }

  // SSE frames are separated by a blank line; each carries one `data:` line.
  const flushFrame = (frame: string) => {
    const dataLine = frame
      .split('\n')
      .find((line) => line.startsWith('data:'))
    if (!dataLine) return
    const payload = dataLine.slice('data:'.length).trim()
    if (!payload) return
    handleEvent(JSON.parse(payload) as StreamEvent)
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let separator = buffer.indexOf('\n\n')
    while (separator !== -1) {
      flushFrame(buffer.slice(0, separator))
      buffer = buffer.slice(separator + 2)
      separator = buffer.indexOf('\n\n')
    }
  }
  // Flush any trailing frame not terminated by a blank line.
  if (buffer.trim()) {
    flushFrame(buffer)
  }

  if (!result) {
    throw new Error('Stream ended without a result')
  }
  return result
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

// Agent (ADK) diagnostics

export async function testQaAgent(
  body: QaAgentTestRequest
): Promise<QaAgentTestResponse> {
  const response = await client.post<QaAgentTestResponse>({
    url: '/agent/qa-test',
    body,
    headers: {
      'Content-Type': 'application/json',
    },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to run the QA agent'))
  }
  return response.data as unknown as QaAgentTestResponse
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

export interface LangfuseDataset {
  id: string
  name: string
  description?: string | null
  item_count?: number | null
  version?: number | null
  source_url?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface LangfuseDatasetsResponse {
  total: number
  datasets: LangfuseDataset[]
}

export async function getLangfuseDatasets(): Promise<LangfuseDatasetsResponse> {
  const response = await client.get<LangfuseDatasetsResponse>({
    url: '/langfuse/datasets',
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch Langfuse datasets'))
  }
  return response.data as unknown as LangfuseDatasetsResponse
}

export interface LangfuseVersion {
  run_name?: string | null
  version?: number | null
  item_count?: number | null
  created_at?: string | null
  [key: string]: unknown
}

export interface LangfuseVersionsResponse {
  dataset_name: string
  total: number
  versions: LangfuseVersion[]
}

export async function getLangfuseVersions(
  dataset: string
): Promise<LangfuseVersionsResponse> {
  const response = await client.get<LangfuseVersionsResponse>({
    url: `/langfuse/versions/${encodeURIComponent(dataset)}`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch Langfuse versions'))
  }
  return response.data as unknown as LangfuseVersionsResponse
}

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
    throw new Error(getErrorMessage(response.error, 'Failed to export to Langfuse'))
  }
  return response.data
}

// Auth endpoints

export interface AuthUser {
  id: string
  email: string
  role: 'user' | 'admin'
  provider: string
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const response = await client.post<AuthUser>({
    url: '/auth/login',
    body: { email, password },
    headers: { 'Content-Type': 'application/json' },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Incorrect email or password'))
  }
  return response.data as unknown as AuthUser
}

export async function logout(): Promise<void> {
  const response = await client.post<void>({ url: '/auth/logout' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Logout failed'))
  }
}

// Returns the current user, or null when not authenticated (401).
export async function getCurrentUser(): Promise<AuthUser | null> {
  const response = await client.get<AuthUser>({ url: '/auth/me' })
  if (response.error) {
    return null
  }
  return response.data as unknown as AuthUser
}

// Absolute URL the browser navigates to in order to start the OIDC flow.
export function oidcLoginUrl(): string {
  const base =
    process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, '') ?? 'http://localhost:8000'
  return `${base}/auth/oidc/login`
}
