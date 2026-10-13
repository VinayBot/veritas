import {
  ApiError,
  type AdvisorResponse,
  type AnalyticsOverview,
  type AnswerDetail,
  type AnswerSummary,
  type ArchitectureGraph,
  type AuditListResponse,
  type AuditSummaryResponse,
  type BenchmarkRunListResponse,
  type BenchmarkRunResponse,
  type CompareEstimate,
  type Comparison,
  type CouncilRunResponse,
  type DeleteDocumentResponse,
  type DocumentListResponse,
  type DocumentResponse,
  type ErrorEnvelope,
  type EvalDataset,
  type GenerateDatasetResponse,
  type GraphResponse,
  type GraphStats,
  type HealthResponse,
  type IndexStatus,
  type Job,
  type ModelSelection,
  type ModelsState,
  type NodeEventsResponse,
  type PiiRevealResponse,
  type ProfileResponse,
  type Recommendation,
  type RedTeamRunResponse,
  type ReportResponse,
  type SearchResponse,
  type SelfCheckResponse,
  type StrategiesResponse,
  type SubsystemsResponse,
  type UploadResponse,
} from './types'

const BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, init)
  if (!resp.ok) {
    const envelope = (await resp.json().catch(() => null)) as ErrorEnvelope | null
    if (envelope) throw new ApiError(envelope, resp.status)
    throw new Error(`Request failed: HTTP ${resp.status}`)
  }
  return (await resp.json()) as T
}

function json<T>(path: string, body: unknown, method = 'POST'): Promise<T> {
  return request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// ---- Health ----

export const getHealth = () => request<HealthResponse>('/health')

// ---- Documents ----

export function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  return request<UploadResponse>('/documents/upload', { method: 'POST', body: form })
}

export const ingestUrl = (url: string, depth = 0) =>
  json<UploadResponse>('/documents/url', { url, depth })

export const getDocument = (id: string) => request<DocumentResponse>(`/documents/${id}`)

export const retryDocument = (id: string) =>
  request<DocumentResponse>(`/documents/${id}/retry`, { method: 'POST' })

export const cancelDocument = (id: string) =>
  request<DocumentResponse>(`/documents/${id}/cancel`, { method: 'POST' })

export const ingestSample = () => request<UploadResponse>('/documents/sample', { method: 'POST' })

export function listDocuments(params: { status?: string; limit?: number; offset?: number } = {}) {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  qs.set('limit', String(params.limit ?? 50))
  if (params.offset) qs.set('offset', String(params.offset))
  return request<DocumentListResponse>(`/documents?${qs.toString()}`)
}

export const deleteDocument = (id: string) =>
  request<DeleteDocumentResponse>(`/documents/${id}`, { method: 'DELETE' })

// ---- PII ----

export const revealPii = (tokens: string[], sessionId: string) =>
  json<PiiRevealResponse>('/pii/reveal', { tokens, session_id: sessionId })

// ---- Retrieval ----

export interface SearchParams {
  query: string
  document_id?: string
  mode?: 'hybrid' | 'dense' | 'bm25'
  k?: number
  use_hyde?: boolean
  rerank?: boolean
  dedupe_strategy?: 'mmr' | 'cosine' | 'ngram' | null
  compress?: boolean
  max_context_tokens?: number
}

export const search = (params: SearchParams) => json<SearchResponse>('/retrieval/search', params)

// ---- Graph ----

export function getGraph(documentId: string, query?: string, hops = 2): Promise<GraphResponse> {
  const qs = new URLSearchParams()
  if (query) qs.set('query', query)
  qs.set('hops', String(hops))
  return request<GraphResponse>(`/graph/${documentId}?${qs.toString()}`)
}

export const getCorpusGraph = (limit = 200) => request<GraphResponse>(`/graph?limit=${limit}`)

export const getGraphStats = (documentId?: string | null) =>
  request<GraphStats>(`/graph/stats${documentId ? `?document_id=${documentId}` : ''}`)

// ---- Architecture / health ----

export const getArchitectureGraph = () => request<ArchitectureGraph>('/architecture/graph')

export const getNodeEvents = (nodeId: string) =>
  request<NodeEventsResponse>(`/architecture/nodes/${encodeURIComponent(nodeId)}/events`)

export const getSubsystems = (force = false) =>
  request<SubsystemsResponse>(`/health/subsystems${force ? '?force=true' : ''}`)

export const runSelfCheck = () => request<SelfCheckResponse>('/health/self-check', { method: 'POST' })

// ---- Reports / Council ----

export const getReport = (reportId: string) => request<ReportResponse>(`/reports/${reportId}`)

export const getCouncilRun = (runId: string) =>
  request<CouncilRunResponse>(`/council/${runId}`)

// ---- Profiler / Advisor ----

export const getProfile = (documentId: string) =>
  request<ProfileResponse>(`/documents/${documentId}/profile`)

export const runAdvisor = (documentId: string) =>
  request<AdvisorResponse>(`/documents/${documentId}/advisor/run`, { method: 'POST' })

export const getAdvisor = (documentId: string) =>
  request<AdvisorResponse>(`/documents/${documentId}/advisor`)

export const decideAdvisor = (documentId: string, decision: 'accept' | 'ignore') =>
  json<AdvisorResponse>(`/documents/${documentId}/advisor/decision`, { decision })

// ---- Evaluation ----

export const generateDataset = (documentId: string, targetSize = 20) =>
  json<GenerateDatasetResponse>(`/documents/${documentId}/eval/datasets/generate`, {
    target_size: targetSize,
  })

export const listDatasets = (documentId: string) =>
  request<{ datasets: EvalDataset[] }>(`/documents/${documentId}/eval/datasets`)

export interface RunBenchmarkParams {
  document_id: string
  configs?: string[] | null
  dataset_id?: string | null
  dataset_target_size?: number
  include_safety?: boolean
}

/** Starts a run as a background job; follow it with useJob. */
export const startBenchmark = (params: RunBenchmarkParams) =>
  json<{ job_id: string }>('/eval/benchmarks/start', params)

export const getBenchmark = (id: string) => request<BenchmarkRunResponse>(`/eval/benchmarks/${id}`)

export const listBenchmarkRuns = (documentId: string) =>
  request<BenchmarkRunListResponse>(`/documents/${documentId}/eval/benchmarks`)

// ---- Jobs ----

export const getJob = (id: string) => request<Job>(`/jobs/${id}`)

export const cancelJob = (id: string) => request<{ status: string }>(`/jobs/${id}/cancel`, { method: 'POST' })

export const listJobs = (kind?: string, active = true) => {
  const qs = new URLSearchParams()
  if (kind) qs.set('kind', kind)
  if (active) qs.set('active', 'true')
  return request<{ jobs: Job[] }>(`/jobs?${qs.toString()}`)
}

export const JOB_STREAM_URL = (id: string, afterSeq = -1) => `${BASE}/jobs/${id}/stream?after_seq=${afterSeq}`

// ---- RAG strategies ----

export const getStrategies = (documentId?: string | null) =>
  request<StrategiesResponse>(`/rag/strategies${documentId ? `?document_id=${documentId}` : ''}`)

export const setDefaultStrategy = (strategy: string) =>
  json<StrategiesResponse>('/rag/default', { strategy }, 'PUT')

export const prepareStrategy = (strategyId: string, documentId: string) =>
  json<{ job_id: string }>(`/rag/strategies/${strategyId}/prepare`, { document_id: documentId })

export const getRecommendation = (documentId: string) =>
  request<Recommendation>(`/documents/${documentId}/recommendation`)

export interface CompareParams {
  document_id: string
  strategies: string[]
  dataset_id?: string | null
  query?: string | null
  baseline?: string | null
}

export const estimateComparison = (params: CompareParams) =>
  json<CompareEstimate>('/rag/compare/estimate', params)

export const startComparison = (params: CompareParams) => json<{ job_id: string }>('/rag/compare', params)

export const getComparison = (id: string) => request<Comparison>(`/rag/comparisons/${id}`)

export const listComparisons = (documentId: string) =>
  request<{ comparisons: Comparison[] }>(`/documents/${documentId}/comparisons`)

// ---- Models ----

export const getModels = () => request<ModelsState>('/models/local')

export const setModelSelection = (changes: Partial<Omit<ModelSelection, 'guard'>>) =>
  json<ModelsState>('/models/selection', changes, 'PUT')

export const resetModelSelection = () => request<ModelsState>('/models/reset', { method: 'POST' })

export const getIndexStatus = () => request<IndexStatus>('/models/index-status')

export const startReindex = (documentIds?: string[]) =>
  json<{ job_id: string }>('/models/reindex', { document_ids: documentIds ?? null })

// ---- Analytics ----

export const getAnalytics = (days = 14) => request<AnalyticsOverview>(`/analytics/overview?days=${days}`)

// ---- Audit / Red-team ----

export function getAudit(params: {
  session_id?: string
  layer?: string
  decision?: string
  real_traffic_only?: boolean
  limit?: number
}): Promise<AuditListResponse> {
  const qs = new URLSearchParams()
  if (params.session_id) qs.set('session_id', params.session_id)
  if (params.layer) qs.set('layer', params.layer)
  if (params.decision) qs.set('decision', params.decision)
  if (params.real_traffic_only) qs.set('real_traffic_only', 'true')
  if (params.limit) qs.set('limit', String(params.limit))
  return request<AuditListResponse>(`/audit?${qs.toString()}`)
}

export const getAuditSummary = () => request<AuditSummaryResponse>('/audit/summary')

export const runRedteam = () => request<RedTeamRunResponse>('/redteam/run', { method: 'POST' })

// ---- Chat (SSE) ----

export interface ChatRequestBody {
  message: string
  document_id?: string | null
  /** Omit to use the workspace default. */
  strategy?: string | null
  /** Omit to let the question's phrasing decide between a quick and a deep answer. */
  detail?: AnswerDetail | null
  reveal_pii?: boolean
  session_id?: string | null
}

export type ChatSseEvent =
  | { event: 'session'; data: { run_id: string; session_id: string; cache_hit: boolean; strategy: string; detail: AnswerDetail } }
  | { event: 'stage'; data: { stage: string; status: string; note?: string } }
  | { event: 'token'; data: string }
  /** The streamed text is superseded (a retry, or the output guardrail changed it). */
  | { event: 'replace'; data: string }
  | { event: 'citations'; data: ReportResponse['citations'] }
  | { event: 'agent_steps'; data: ReportResponse['agent_steps'] }
  | { event: 'routing'; data: ReportResponse['routing'] }
  | { event: 'council_run_id'; data: string }
  /** The answer is complete; scoring has not started yet. */
  | { event: 'answer'; data: AnswerSummary }
  | { event: 'quality'; data: ReportResponse['quality'] }
  | { event: 'done'; data: { report_id: string; cache_hit: boolean } }
  | { event: 'error'; data: { code: string; message: string } }

/** Reads `event:` / `data:` frames from a fetch body. Every payload is JSON. */
export async function readSse(
  resp: Response,
  onFrame: (event: string, data: unknown) => void,
): Promise<void> {
  if (!resp.body) throw new Error('The response had no body')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sepIndex: number
    while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sepIndex)
      buffer = buffer.slice(sepIndex + 2)
      const lines = frame.split('\n')
      const eventLine = lines.find((l) => l.startsWith('event: '))
      const dataLine = lines.find((l) => l.startsWith('data: '))
      if (!eventLine || !dataLine) continue
      let data: unknown
      try {
        data = JSON.parse(dataLine.slice('data: '.length))
      } catch {
        continue // a malformed frame is dropped rather than shown as text
      }
      onFrame(eventLine.slice('event: '.length), data)
    }
  }
}

export async function streamChat(
  body: ChatRequestBody,
  onEvent: (e: ChatSseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  await readSse(resp, (event, data) => onEvent({ event, data } as ChatSseEvent))
}

export const cancelRun = (runId: string) => request<{ status: string }>(`/runs/${runId}/cancel`, { method: 'POST' })

export { ApiError }
