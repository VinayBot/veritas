import {
  ApiError,
  type AdvisorResponse,
  type AuditListResponse,
  type BenchmarkRunResponse,
  type ChatMode,
  type CouncilRunResponse,
  type DocumentResponse,
  type ErrorEnvelope,
  type GenerateDatasetResponse,
  type GraphResponse,
  type HealthResponse,
  type PiiRevealResponse,
  type ProfileResponse,
  type RedTeamRunResponse,
  type ReportResponse,
  type SearchResponse,
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

export interface RunBenchmarkParams {
  document_id: string
  configs?: string[] | null
  dataset_target_size?: number
}

export const runBenchmark = (params: RunBenchmarkParams) =>
  json<BenchmarkRunResponse>('/eval/benchmarks/run', params)

export const getBenchmark = (id: string) => request<BenchmarkRunResponse>(`/eval/benchmarks/${id}`)

// ---- Audit / Red-team ----

export function getAudit(params: {
  session_id?: string
  layer?: string
  limit?: number
}): Promise<AuditListResponse> {
  const qs = new URLSearchParams()
  if (params.session_id) qs.set('session_id', params.session_id)
  if (params.layer) qs.set('layer', params.layer)
  if (params.limit) qs.set('limit', String(params.limit))
  return request<AuditListResponse>(`/audit?${qs.toString()}`)
}

export const runRedteam = () => request<RedTeamRunResponse>('/redteam/run', { method: 'POST' })

// ---- Chat (SSE) ----

export interface ChatRequestBody {
  message: string
  document_id?: string | null
  mode?: ChatMode
  council?: boolean
  reveal_pii?: boolean
  session_id?: string | null
}

export type ChatSseEvent =
  | { event: 'session'; data: { session_id: string; cache_hit: boolean } }
  | { event: 'token'; data: string }
  | { event: 'citations'; data: ReportResponse['citations'] }
  | { event: 'agent_steps'; data: ReportResponse['agent_steps'] }
  | { event: 'quality'; data: ReportResponse['quality'] }
  | { event: 'routing'; data: ReportResponse['routing'] }
  | { event: 'council_run_id'; data: string }
  | { event: 'done'; data: { report_id: string; cache_hit: boolean } }
  | { event: 'error'; data: { code: string; message: string } }

/** Parses one SSE frame ("event: x\ndata: y") per app/api/routes/chat.py's _sse() helper —
 * string payloads are sent raw (not JSON-encoded), everything else is JSON. */
function parseSseData(event: string, raw: string): unknown {
  if (event === 'token' || event === 'council_run_id') return raw
  try {
    return JSON.parse(raw)
  } catch {
    return raw
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
  if (!resp.body) throw new Error('Chat response had no body')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sepIndex: number
    // SSE frames are separated by a blank line ("\n\n").
    while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sepIndex)
      buffer = buffer.slice(sepIndex + 2)
      const lines = frame.split('\n')
      const eventLine = lines.find((l) => l.startsWith('event: '))
      const dataLine = lines.find((l) => l.startsWith('data: '))
      if (!eventLine || !dataLine) continue
      const event = eventLine.slice('event: '.length)
      const raw = dataLine.slice('data: '.length)
      onEvent({ event, data: parseSseData(event, raw) } as ChatSseEvent)
    }
  }
}

export { ApiError }
