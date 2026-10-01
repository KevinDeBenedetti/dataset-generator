// Hand-written, friendlier wrappers around the auto-generated client.
//
// `@hey-api/openapi-ts` regenerates `sdk.gen.ts` and `types.gen.ts`, so
// these higher-level helpers (which unwrap responses, flatten errors and add the
// SSE streaming endpoint) live here, in a file the generator never touches.
import { client } from './gen/client.gen'

// The auth cookie is httpOnly and set by the API (cross-origin in dev), so every
// request must send/accept credentials for the session to work.
//
// The browser-facing API origin defaults to localhost:8000 but is overridable via
// NEXT_PUBLIC_API_BASE_URL, so the host port can change (e.g. to avoid collisions
// when running several dev stacks) without editing the generated client.
//
// Unset, it defaults to the same-origin `/api` in production (the ingress routes
// it to the API — one image for any host, no CORS) and to the dev server on
// localhost:8000 otherwise.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, '') ||
  (process.env.NODE_ENV === 'production' ? '/api' : 'http://localhost:8000')

client.setConfig({
  credentials: 'include',
  baseUrl: API_BASE_URL,
})

// ── Silent session refresh ───────────────────────────────────────────────────
// The access token is a short-lived httpOnly cookie; a long-lived refresh
// cookie (rotated server-side on every use) can renew it. When any API call
// comes back 401, try POST /auth/refresh once and replay the request, so an
// expired access token never surfaces as a logout mid-session.

// A 401 from these endpoints is a definitive answer — refreshing would either
// loop (/auth/refresh) or mask a real credential failure.
const NO_REFRESH_PATHS = ['/auth/login', '/auth/logout', '/auth/refresh', '/auth/providers']

let refreshInFlight: Promise<boolean> | null = null

// Concurrent 401s (e.g. several queries firing on a page load) share a single
// refresh attempt — rotation makes the refresh cookie single-use, so parallel
// calls would revoke each other's tokens.
function tryRefreshSession(baseUrl: string): Promise<boolean> {
  refreshInFlight ??= fetch(`${baseUrl}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshInFlight = null
    })
  return refreshInFlight
}

client.interceptors.response.use(async (response, request, options) => {
  if (response.status !== 401) return response
  const path = new URL(request.url).pathname
  if (NO_REFRESH_PATHS.some((p) => path.endsWith(p))) return response

  const baseUrl = new URL(request.url).origin
  if (!(await tryRefreshSession(baseUrl))) return response

  // Replay the original request with the renewed access cookie. The first
  // attempt consumed the Request body, so rebuild it from the client options.
  const { serializedBody, body, method } = options as {
    serializedBody?: BodyInit
    body?: unknown
    method?: string
  }
  const retryBody = serializedBody ?? (body as BodyInit | undefined)
  const retryMethod = method ?? request.method
  return fetch(request.url, {
    method: retryMethod,
    headers: request.headers,
    credentials: 'include',
    ...(retryBody !== undefined && !['GET', 'HEAD'].includes(retryMethod)
      ? { body: retryBody }
      : {}),
  })
})
import type {
  DatasetResponse,
  DatasetSourcesResponse,
  HuggingFaceExportResponse,
  DatasetGenerationResponse,
  SimilarityAnalysisResponse,
  CleanSimilarityResponse,
  DeleteDatasetResponse,
  QaListResponse,
  QaAgentTestRequest,
  QaAgentTestResponse,
  ValidationError,
  JobInfo,
  JobRunOut,
  ModelsResponse,
  ModelTestResponse,
  UrlGenerationRequest,
} from './gen/types.gen'

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

// Generate a dataset from an uploaded file (PDF or image). Multipart upload, so
// this uses a hand-rolled fetch (FormData) rather than the JSON client.
export interface GenerateFromFileParams {
  file: File
  datasetName: string
  targetLanguage?: string | null
  modelQa?: string | null
  modelVlm?: string | null
  similarityThreshold?: number
  persist?: boolean
}

export async function generateDatasetFromFile(
  params: GenerateFromFileParams,
): Promise<DatasetGenerationResponse> {
  const baseUrl = client.getConfig().baseUrl ?? ''
  const form = new FormData()
  form.append('file', params.file)
  form.append('dataset_name', params.datasetName)
  if (params.targetLanguage) form.append('target_language', params.targetLanguage)
  if (params.modelQa) form.append('model_qa', params.modelQa)
  if (params.modelVlm) form.append('model_vlm', params.modelVlm)
  if (params.similarityThreshold != null) {
    form.append('similarity_threshold', String(params.similarityThreshold))
  }
  if (params.persist != null) {
    form.append('persist', String(params.persist))
  }

  // No Content-Type header: the browser sets the multipart boundary itself.
  const response = await fetch(`${baseUrl}/dataset/generate/file`, {
    method: 'POST',
    body: form,
    credentials: 'include',
  })

  if (!response.ok) {
    let message = 'Failed to generate dataset from file'
    try {
      message = getErrorMessage(await response.json(), message)
    } catch {
      // Non-JSON error body — keep the fallback message.
    }
    throw new Error(message)
  }
  return (await response.json()) as DatasetGenerationResponse
}

// Generate a dataset from one web page (no crawling). Model fields are
// "<provider>:<model>" references; omitted ones use the role defaults.
export async function generateDatasetFromUrl(
  body: UrlGenerationRequest,
): Promise<DatasetGenerationResponse> {
  const response = await client.post<DatasetGenerationResponse>({
    url: '/dataset/generate/url',
    body,
    headers: { 'Content-Type': 'application/json' },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to generate dataset from URL'))
  }
  return response.data as unknown as DatasetGenerationResponse
}

// Datasets are keyed by their name (the identifier the API takes).
export async function deleteDataset(datasetName: string): Promise<DeleteDatasetResponse> {
  const response = await client.delete<DeleteDatasetResponse>({
    url: `/dataset/${encodeURIComponent(datasetName)}`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to delete dataset'))
  }
  return response.data as unknown as DeleteDatasetResponse
}

// The origins a dataset was built from (one row per crawled page/file/account)
// plus the history of the analyses that fed it. Datasets are keyed by their
// name (the identifier the API takes).
export async function getDatasetSources(datasetName: string): Promise<DatasetSourcesResponse> {
  const response = await client.get<DatasetSourcesResponse>({
    url: `/dataset/${encodeURIComponent(datasetName)}/sources`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch the dataset sources'))
  }
  return response.data as unknown as DatasetSourcesResponse
}

export async function analyzeSimilarities(
  datasetId: string,
  threshold?: number,
): Promise<SimilarityAnalysisResponse> {
  const seg = encodeURIComponent(datasetId)
  // Check for undefined explicitly: a valid threshold of 0 is falsy and must
  // still be forwarded rather than falling back to the server default.
  const url =
    threshold !== undefined
      ? `/dataset/${seg}/analyze-similarities?threshold=${threshold}`
      : `/dataset/${seg}/analyze-similarities`

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
  threshold?: number,
): Promise<CleanSimilarityResponse> {
  const seg = encodeURIComponent(datasetId)
  // Check for undefined explicitly: a valid threshold of 0 is falsy and must
  // still be forwarded rather than falling back to the server default.
  const url =
    threshold !== undefined
      ? `/dataset/${seg}/clean-similarities?threshold=${threshold}`
      : `/dataset/${seg}/clean-similarities`

  const response = await client.post<CleanSimilarityResponse>({
    url,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to clean similarities'))
  }
  return response.data as unknown as CleanSimilarityResponse
}

// Hand-written: mirrors ResolvePairResponse (apps/server/schemas/dataset.py).
export interface ResolvePairResponse {
  dataset_id: string
  dataset_name: string
  removed_id: string
  removed_question: string
}

// Arbitrate one duplicate pair: delete `removeId` (full id or the 8-char
// prefix from analyze-similarities), keep the other record. Admin only.
export async function resolvePair(
  datasetId: string,
  removeId: string,
): Promise<ResolvePairResponse> {
  const response = await client.post<ResolvePairResponse>({
    url: `/dataset/${encodeURIComponent(datasetId)}/resolve-pair`,
    body: { remove_id: removeId },
    headers: {
      'Content-Type': 'application/json',
    },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to resolve the duplicate pair'))
  }
  return response.data as unknown as ResolvePairResponse
}

// Model providers (OpenAI API, Claude subscription), their models and the
// default model reference of each role (cleaning, qa, vision, jobs).
// `discover` also asks the OpenAI-compatible endpoint which models it serves.
export async function getModels(discover = false): Promise<ModelsResponse> {
  const response = await client.get<ModelsResponse>({
    url: `/models${discover ? '?discover=true' : ''}`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch models'))
  }
  return response.data as unknown as ModelsResponse
}

// Set your default model of one or more roles.
export async function updateModelDefaults(
  defaults: Record<string, string>,
): Promise<ModelsResponse> {
  const response = await client.put<ModelsResponse>({
    url: '/models/defaults',
    body: { defaults },
    headers: { 'Content-Type': 'application/json' },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to save the model defaults'))
  }
  return response.data as unknown as ModelsResponse
}

// Send one short prompt to a model (spends your own provider quota).
export async function testModel(ref: string, prompt?: string): Promise<ModelTestResponse> {
  const response = await client.post<ModelTestResponse>({
    url: '/models/test',
    body: prompt ? { ref, prompt } : { ref },
    headers: { 'Content-Type': 'application/json' },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to test the model'))
  }
  return response.data as unknown as ModelTestResponse
}

// Hand-written: mirrors PromptsResponse (apps/server/schemas/prompts.py).
export interface PromptInfo {
  key: string
  label: string
  role: string
  model: string
  used_by: string
  active: boolean
  content: string
}

export interface PromptsResponse {
  total: number
  prompts: PromptInfo[]
}

// The LLM prompts the app actually ships (read-only — they live in code).
export async function getPrompts(): Promise<PromptsResponse> {
  const response = await client.get<PromptsResponse>({ url: '/prompts' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch prompts'))
  }
  return response.data as unknown as PromptsResponse
}

// QA agent diagnostics

export async function testQaAgent(body: QaAgentTestRequest): Promise<QaAgentTestResponse> {
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
  options?: { limit?: number; offset?: number },
): Promise<QaListResponse> {
  const params = new URLSearchParams()
  if (options?.limit) params.set('limit', String(options.limit))
  if (options?.offset) params.set('offset', String(options.offset))

  const seg = encodeURIComponent(datasetId)
  const queryString = params.toString()
  const url = queryString ? `/q_a/${seg}?${queryString}` : `/q_a/${seg}`

  const response = await client.get<QaListResponse>({
    url,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch Q&A data'))
  }
  return response.data as unknown as QaListResponse
}

// Hand-written: mirrors QAStatsResponse (apps/server/schemas/q_a.py). Regenerate
// api/types.gen.ts (npm run api:generate) to pick up the generated equivalent.
export interface QAScoreBucket {
  label: string
  count: number
}

export interface QAStats {
  dataset_name: string
  dataset_id: string
  total_count: number
  scored_count: number
  average_score: number | null
  score_threshold: number
  below_threshold_count: number
  validated_count: number
  distribution: QAScoreBucket[]
}

// Hand-written: mirrors QualityRulesResponse (apps/server/schemas/quality_rules.py).
export interface QualityRules {
  min_answer_words: number
  reject_below_confidence: number
  auto_reject_enabled: boolean
  updated_at: string | null
}

export type QualityRulesUpdate = Partial<
  Pick<QualityRules, 'min_answer_words' | 'reject_below_confidence' | 'auto_reject_enabled'>
>

export async function getQualityRules(): Promise<QualityRules> {
  const response = await client.get<QualityRules>({ url: '/quality-rules' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch quality rules'))
  }
  return response.data as unknown as QualityRules
}

export async function updateQualityRules(body: QualityRulesUpdate): Promise<QualityRules> {
  const response = await client.put<QualityRules>({
    url: '/quality-rules',
    body,
    headers: {
      'Content-Type': 'application/json',
    },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to update quality rules'))
  }
  return response.data as unknown as QualityRules
}

export async function getQAStats(datasetId: string, scoreThreshold?: number): Promise<QAStats> {
  const seg = encodeURIComponent(datasetId)
  // Check for undefined explicitly: a valid threshold of 0 is falsy and must
  // still be forwarded rather than falling back to the server default.
  const url =
    scoreThreshold !== undefined
      ? `/q_a/${seg}/stats?score_threshold=${scoreThreshold}`
      : `/q_a/${seg}/stats`

  const response = await client.get<QAStats>({ url })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch Q&A stats'))
  }
  return response.data as unknown as QAStats
}

export interface QAScoreResult {
  dataset_name: string
  model: string
  requested: number
  scored: number
  failed: number
}

// Scores a dataset's pairs with an LLM judge (admin only). By default only
// pairs without a confidence — typically imported from Hugging Face.
export async function scoreQA(
  datasetId: string,
  options?: { onlyUnscored?: boolean },
): Promise<QAScoreResult> {
  const onlyUnscored = options?.onlyUnscored ?? true
  const response = await client.post<QAScoreResult>({
    url: `/q_a/${encodeURIComponent(datasetId)}/score?only_unscored=${onlyUnscored}`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to score the Q&A pairs'))
  }
  return response.data as unknown as QAScoreResult
}

// Dataset versions & copies

export interface DatasetVersion {
  run_name?: string | null
  version?: number | null
  item_count?: number | null
  pages_analyzed?: number | null
  new_pairs?: number | null
  duplicates_skipped?: number | null
  created_at?: string | null
  source_url?: string | null
  label?: string
  kind?: string
}

export interface DatasetVersionsResponse {
  dataset_name: string
  total: number
  versions: DatasetVersion[]
}

// The dataset's recorded generations, newest first.
export async function getDatasetVersions(datasetName: string): Promise<DatasetVersionsResponse> {
  const response = await client.get<DatasetVersionsResponse>({
    url: `/dataset/${encodeURIComponent(datasetName)}/versions`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch the dataset versions'))
  }
  return response.data as unknown as DatasetVersionsResponse
}

// Export a dataset to the Hugging Face Hub. The repo is always created
// private — the server refuses to upload into an existing public repo rather
// than publishing generated data (409).
export async function exportDatasetToHuggingFace(
  datasetName: string,
  repoId?: string | null,
): Promise<HuggingFaceExportResponse> {
  const params = repoId ? `?repo_id=${encodeURIComponent(repoId)}` : ''
  const response = await client.post<HuggingFaceExportResponse>({
    url: `/dataset/${encodeURIComponent(datasetName)}/export/huggingface${params}`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to export to Hugging Face'))
  }
  return response.data as unknown as HuggingFaceExportResponse
}

export interface HuggingFaceDataset {
  id: string
  url: string
  author: string | null
  private: boolean
  /** false, or the gating mode ('auto' | 'manual') */
  gated: boolean | string
  disabled: boolean
  /** Downloads in the last 30 days */
  downloads: number | null
  downloads_all_time: number | null
  likes: number | null
  tags: string[]
  description: string | null
  pretty_name: string | null
  language: string[] | null
  license: string | null
  size_category: string | null
  file_count: number | null
  /** Repo size in bytes */
  used_storage: number | null
  sha: string | null
  created_at: string | null
  last_modified: string | null
}

export interface HuggingFaceDatasetsResponse {
  namespace: string
  total: number
  datasets: HuggingFaceDataset[]
}

// List the Hugging Face Hub dataset repos owned by the configured account
// (same namespace `exportDatasetToHuggingFace` writes to).
export async function getHuggingFaceDatasets(): Promise<HuggingFaceDatasetsResponse> {
  const response = await client.get<HuggingFaceDatasetsResponse>({
    url: '/dataset/huggingface',
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch Hugging Face datasets'))
  }
  return response.data as unknown as HuggingFaceDatasetsResponse
}

export interface HuggingFaceImportResponse {
  dataset_name: string
  repo_id: string
  pairs_imported: number
  version: number
}

// Pull a Hub dataset repo's Q/A pairs into a local dataset (by content-hash
// id, so re-importing is idempotent), so it can be analyzed like any other
// dataset — quality control's duplicate detection, score stats and rules.
export async function importHuggingFaceDataset(
  repoId: string,
  datasetName?: string | null,
): Promise<HuggingFaceImportResponse> {
  const params = new URLSearchParams({ repo_id: repoId })
  if (datasetName) params.set('dataset_name', datasetName)
  const response = await client.post<HuggingFaceImportResponse>({
    url: `/dataset/huggingface/import?${params.toString()}`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to import the Hugging Face dataset'))
  }
  return response.data as unknown as HuggingFaceImportResponse
}

export interface DuplicateDatasetResponse {
  message: string
  dataset_name: string
  target_dataset_name: string
  total_items: number
  created_count: number
}

// Copy a dataset's pairs into another dataset (the export flow).
export async function duplicateDataset(
  datasetName: string,
  targetName?: string | null,
): Promise<DuplicateDatasetResponse> {
  const params = targetName ? `?target_name=${encodeURIComponent(targetName)}` : ''
  const response = await client.post<DuplicateDatasetResponse>({
    url: `/dataset/${encodeURIComponent(datasetName)}/duplicate${params}`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to copy the dataset'))
  }
  return response.data as unknown as DuplicateDatasetResponse
}

// Collections (datasets projected into a Qdrant vector store)

export interface Collection {
  id: string
  name: string
  description?: string | null
  target_language?: string | null
  qa_sources_count?: number | null
  created_at?: string | null
  collection_name: string
  // null when Qdrant is unconfigured/unreachable (status unknown).
  in_qdrant?: boolean | null
  points_count?: number | null
}

export interface CollectionsResponse {
  qdrant_configured: boolean
  total: number
  collections: Collection[]
}

export async function getCollections(): Promise<CollectionsResponse> {
  const response = await client.get<CollectionsResponse>({ url: '/collections' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch collections'))
  }
  return response.data as unknown as CollectionsResponse
}

export interface QdrantSyncResponse {
  dataset_name: string
  collection_name: string
  points_upserted: number
  vector_size: number
}

// Datasets are keyed by their name (the identifier the API takes).
export async function syncCollectionToQdrant(datasetName: string): Promise<QdrantSyncResponse> {
  const response = await client.post<QdrantSyncResponse>({
    url: `/collections/${encodeURIComponent(datasetName)}/qdrant`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to add collection to Qdrant'))
  }
  return response.data as unknown as QdrantSyncResponse
}

export interface CollectionSearchResult {
  qa_id?: string | null
  question: string
  answer: string
  context: string
  source_url?: string | null
  confidence?: number | null
  score?: number | null
}

export interface CollectionSearchResponse {
  dataset_name: string
  collection_name: string
  query: string
  count: number
  results: CollectionSearchResult[]
}

// Semantic search over a dataset's Qdrant collection. Datasets are keyed by
// their name (the identifier the API takes).
export async function searchCollection(
  datasetName: string,
  query: string,
  options?: { limit?: number; scoreThreshold?: number },
): Promise<CollectionSearchResponse> {
  const response = await client.post<CollectionSearchResponse>({
    url: `/collections/${encodeURIComponent(datasetName)}/search`,
    body: {
      query,
      ...(options?.limit !== undefined ? { limit: options.limit } : {}),
      ...(options?.scoreThreshold !== undefined ? { score_threshold: options.scoreThreshold } : {}),
    },
    headers: { 'Content-Type': 'application/json' },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to search collection'))
  }
  return response.data as unknown as CollectionSearchResponse
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
//
// Only a 401 means "not logged in". Any other failure (5xx, network outage)
// is thrown so callers (react-query) can retry instead of mistaking a transient
// error for a logout and tearing down the session.
export async function getCurrentUser(): Promise<AuthUser | null> {
  const response = await client.get<AuthUser>({ url: '/auth/me' })
  if (response.error) {
    if (response.response?.status === 401) {
      return null
    }
    throw new Error(getErrorMessage(response.error, 'Failed to fetch the current user'))
  }
  return response.data as unknown as AuthUser
}

// Dataset job catalogue (server/jobs/registry.py) — the same code their
// GitHub Actions workflows run on a schedule, triggered here on demand. Each
// job serves the JSON schema of its options, which the Jobs page renders.
export async function getJobs(): Promise<JobInfo[]> {
  const response = await client.get<{ jobs: JobInfo[] }>({ url: '/jobs' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch the jobs'))
  }
  return (response.data as unknown as { jobs: JobInfo[] }).jobs
}

// Starts a run in the background (202) — poll getJobRun for its progress.
export async function startJobRun(
  jobId: string,
  options: Record<string, unknown>,
  modelRef?: string | null,
): Promise<JobRunOut> {
  const response = await client.post<JobRunOut>({
    url: `/jobs/${encodeURIComponent(jobId)}/run`,
    body: { options, model_ref: modelRef || null },
    headers: { 'Content-Type': 'application/json' },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, `Failed to start the ${jobId} job`))
  }
  return response.data as unknown as JobRunOut
}

export async function getJobRun(runId: string): Promise<JobRunOut> {
  const response = await client.get<JobRunOut>({
    url: `/jobs/runs/${encodeURIComponent(runId)}`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to fetch the job run'))
  }
  return response.data as unknown as JobRunOut
}

// Cancels a queued run, or asks the worker to stop a running one.
export async function cancelJobRun(runId: string): Promise<JobRunOut> {
  const response = await client.post<JobRunOut>({
    url: `/jobs/runs/${encodeURIComponent(runId)}/cancel`,
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to cancel the run'))
  }
  return response.data as unknown as JobRunOut
}

// Publishes a run's reviewed draft: `exclude` drops new pairs, `promote` moves
// pairs from the review list into the export.
export async function publishJobRun(
  runId: string,
  selection: { exclude: string[]; promote: string[] },
): Promise<JobRunOut> {
  const response = await client.post<JobRunOut>({
    url: `/jobs/runs/${encodeURIComponent(runId)}/publish`,
    body: selection,
    headers: { 'Content-Type': 'application/json' },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to publish to Hugging Face'))
  }
  return response.data as unknown as JobRunOut
}

// Absolute URL the browser navigates to in order to sign in with a provider
// ("infomaniak", "github"), or — while signed in — to link it to the account.
export function ssoUrl(provider: string, action: 'login' | 'link' = 'login'): string {
  return `${API_BASE_URL}/auth/${encodeURIComponent(provider)}/${action}`
}

// Hand-written: mirrors ProvidersResponse (apps/server/api/auth.py).
export interface AuthProviders {
  providers: { name: string; label: string; configured: boolean }[]
  local_login: boolean
  signup_open: boolean
}

export async function getAuthProviders(): Promise<AuthProviders> {
  const response = await client.get<AuthProviders>({ url: '/auth/providers' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to load the sign-in options'))
  }
  return response.data as unknown as AuthProviders
}

// Sign out on every device (all sessions, this one included).
export async function logoutEverywhere(): Promise<void> {
  const response = await client.post<void>({ url: '/auth/logout-all' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to sign out everywhere'))
  }
}

// Hand-written: mirrors IdentitiesResponse (apps/server/schemas/me.py).
export interface LinkedIdentity {
  id: string
  provider: string
  email?: string | null
  username?: string | null
  created_at: string
  last_login_at?: string | null
}

export interface IdentitiesInfo {
  identities: LinkedIdentity[]
  has_password: boolean
  locked_admin: boolean
}

export async function getIdentities(): Promise<IdentitiesInfo> {
  const response = await client.get<IdentitiesInfo>({ url: '/me/identities' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to load your sign-in methods'))
  }
  return response.data as unknown as IdentitiesInfo
}

export async function unlinkIdentity(id: string): Promise<void> {
  const response = await client.delete({ url: `/me/identities/${encodeURIComponent(id)}` })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to unlink'))
  }
}

// --- Your keys and integration settings --------------------------------------

export type SecretKind =
  | 'openai_api_key'
  | 'claude_token'
  | 'anthropic_api_key'
  | 'hf_token'
  | 'github_token'

export type SettingKey =
  | 'openai_base_url'
  | 'hf_namespace'
  | 'hf_qa_repo'
  | 'hf_corpus_repo'
  | 'github_username'

// Hand-written: mirrors apps/server/schemas/me.py. Secrets are write-only — the
// API returns whether one is saved (and a last-four hint), never its value.
export interface SecretStatus {
  kind: SecretKind
  configured: boolean
  hint?: string | null
  updated_at?: string | null
}

export interface SecretCheck {
  kind: SecretKind
  ok: boolean
  checked: boolean
  message: string
}

export async function getSecrets(): Promise<SecretStatus[]> {
  const response = await client.get<{ secrets: SecretStatus[] }>({ url: '/me/secrets' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to load your keys'))
  }
  return (response.data as unknown as { secrets: SecretStatus[] }).secrets
}

// Save (or replace) a key. It is checked against its provider first; `force`
// saves it anyway when only that check failed.
export async function saveSecret(
  kind: SecretKind,
  value: string,
  force = false,
): Promise<{ secret: SecretStatus; check: SecretCheck }> {
  const response = await client.put<{ secret: SecretStatus; check: SecretCheck }>({
    url: `/me/secrets/${kind}`,
    body: { value, force },
    headers: { 'Content-Type': 'application/json' },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to save the key'))
  }
  return response.data as unknown as { secret: SecretStatus; check: SecretCheck }
}

export async function testSecret(kind: SecretKind): Promise<SecretCheck> {
  const response = await client.post<SecretCheck>({ url: `/me/secrets/${kind}/test` })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to test the key'))
  }
  return response.data as unknown as SecretCheck
}

export async function deleteSecret(kind: SecretKind): Promise<void> {
  const response = await client.delete({ url: `/me/secrets/${kind}` })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to remove the key'))
  }
}

export async function getSettings(): Promise<Record<SettingKey, string>> {
  const response = await client.get<{ settings: Record<SettingKey, string> }>({
    url: '/me/settings',
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to load your settings'))
  }
  return (response.data as unknown as { settings: Record<SettingKey, string> }).settings
}

export async function saveSettings(
  settings: Partial<Record<SettingKey, string>>,
): Promise<Record<SettingKey, string>> {
  const response = await client.put<{ settings: Record<SettingKey, string> }>({
    url: '/me/settings',
    body: { settings },
    headers: { 'Content-Type': 'application/json' },
  })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to save your settings'))
  }
  return (response.data as unknown as { settings: Record<SettingKey, string> }).settings
}

// --- Backoffice (admins only) -------------------------------------------------
// Hand-written: mirrors apps/server/schemas/admin.py — accounts and usage, never
// dataset content or secrets.

export interface AdminUser {
  id: string
  email: string
  role: 'user' | 'admin'
  is_active: boolean
  locked: boolean
  providers: string[]
  has_password: boolean
  created_at?: string | null
  last_login_at?: string | null
  configured_keys: string[]
  datasets: number
  pairs: number
  runs: number
}

export interface AuditEntry {
  id: string
  created_at: string
  action: string
  actor?: string | null
  target?: string | null
  target_user_id?: string | null
  ip?: string | null
  detail: Record<string, unknown>
}

export interface PlatformSwitch {
  key: string
  label: string
  value: unknown
  overridden: boolean
}

export interface AdminUsage {
  users: { total: number; active: number; admins: number; signed_in_30d: number }
  datasets: number
  pairs: number
  runs_30d: Record<string, number>
  running: number
}

async function adminCall<T>(
  method: 'get' | 'put' | 'patch' | 'delete',
  url: string,
  fallback: string,
  body?: unknown,
): Promise<T> {
  const response = await client[method]<T>({
    url,
    ...(body === undefined ? {} : { body, headers: { 'Content-Type': 'application/json' } }),
  })
  if (response.error) throw new Error(getErrorMessage(response.error, fallback))
  return response.data as unknown as T
}

export const adminApi = {
  users: (q = '', offset = 0, limit = 50) =>
    adminCall<{ total: number; users: AdminUser[] }>(
      'get',
      `/admin/users?q=${encodeURIComponent(q)}&offset=${offset}&limit=${limit}`,
      'Failed to load the users',
    ),
  updateUser: (id: string, changes: { role?: 'user' | 'admin'; is_active?: boolean }) =>
    adminCall<AdminUser>('patch', `/admin/users/${id}`, 'Failed to update the user', changes),
  deleteUser: (id: string) =>
    adminCall<void>('delete', `/admin/users/${id}`, 'Failed to delete the user'),
  audit: (offset = 0, action = '', userId = '') =>
    adminCall<{ total: number; entries: AuditEntry[] }>(
      'get',
      `/admin/audit?offset=${offset}&action=${encodeURIComponent(action)}&user_id=${encodeURIComponent(userId)}`,
      'Failed to load the audit log',
    ),
  usage: () => adminCall<AdminUsage>('get', '/admin/usage', 'Failed to load the usage'),
  platform: () =>
    adminCall<{ settings: PlatformSwitch[] }>('get', '/admin/platform', 'Failed to load'),
  updatePlatform: (settings: Record<string, unknown>) =>
    adminCall<{ settings: PlatformSwitch[] }>(
      'put',
      '/admin/platform',
      'Failed to save the platform settings',
      { settings },
    ),
}

// Self-service: a zip of everything you own, and account deletion.
export function exportUrl(): string {
  return `${API_BASE_URL}/me/export`
}

export async function deleteMyAccount(): Promise<void> {
  const response = await client.delete({ url: '/me' })
  if (response.error) {
    throw new Error(getErrorMessage(response.error, 'Failed to delete your account'))
  }
}
