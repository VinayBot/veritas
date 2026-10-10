// Mirrors backend/app/api/schemas/*.py field-for-field. Keep in sync by hand — there is no
// shared codegen between the two, so a backend field rename needs the matching edit here.

export interface ErrorEnvelope {
  code: string
  message: string
  trace_id: string
}

export class ApiError extends Error {
  code: string
  traceId: string
  status: number
  constructor(envelope: ErrorEnvelope, status: number) {
    super(envelope.message)
    this.code = envelope.code
    this.traceId = envelope.trace_id
    this.status = status
  }
}

// ---- Health ----

export interface PreflightCheck {
  name: string
  ok: boolean
  detail: string
  duration_ms: number
}

/** Before the server's first preflight pass finishes, `/health` reports just `{status:
 * "running"}` — see backend/app/core/preflight.py. */
export type PreflightReport =
  | { status: 'running' }
  | { status: 'ok' | 'degraded'; ok: boolean; checks: PreflightCheck[] }

export interface HealthResponse {
  status: string
  app_env: string
  hardware_tier: string
  ollama: { status: string; models: string[] }
  vector_store: string
  graph_store: string
  preflight: PreflightReport
}

// ---- Documents ----

export interface UploadResponse {
  document_id: string
  job_id: string
}

/** Mirrors app/ingestion/service.py's job state machine — see docs/TROUBLESHOOTING.md. Ingestion
 * is a detached background job: a document starts "queued", moves through "running" (with
 * `current_stage` naming the real pipeline stage), and lands on exactly one terminal status. */
export type DocumentStatus = 'queued' | 'running' | 'ready' | 'failed' | 'cancelled'

/** Graph extraction, profiling, and the advisor tournament run as a *separate* background phase
 * after the document is already "ready" for chat — never required for chat, never blocking. */
export type EnrichmentStatus = 'running' | 'done' | 'failed' | 'cancelled' | null

export interface DocumentResponse {
  id: string
  filename: string
  source_type: string
  source_url: string | null
  mime_type: string | null
  status: DocumentStatus
  current_stage: string | null
  error_message: string | null
  error_stage: string | null
  enrichment_status: EnrichmentStatus
  enrichment_error: string | null
  raw_text_chars: number | null
  quality_score_before: number | null
  quality_score_after: number | null
  fix_log: Record<string, unknown>[]
  language: string | null
  ocr_confidence: number | null
  pii_counts: Record<string, number>
  chunk_count: number | null
  chunk_strategy: string | null
  graph_entity_count: number | null
  graph_triple_count: number | null
  created_at: string
  updated_at: string
}

// ---- PII ----

export interface PiiRevealResponse {
  revealed: Record<string, string>
  not_found: string[]
}

// ---- Retrieval ----

export interface SearchHit {
  chunk_id: string
  score: number
  text: string
  dense_rank: number | null
  bm25_rank: number | null
  dense_score: number | null
  bm25_score: number | null
  rerank_score: number | null
}

export interface SearchResponse {
  hits: SearchHit[]
}

// ---- Graph ----

export interface GraphNode {
  id: string
  label: string
  name: string
  doc_ids: string[]
  mentions: string[]
  community: number | null
}

export interface GraphEdge {
  source: string
  target: string
  predicate: string | null
  doc_id: string | null
  chunk_id: string | null
}

export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
  linked_entities: GraphNode[] | null
}

// ---- Chat ----

export type ChatMode = 'agentic' | 'hybrid' | 'graph'

export interface ChatCitation {
  marker: number
  chunk_id: string
  text: string
}

export interface AgentStep {
  node: string
  summary: string
}

export interface QualityReport {
  label: string
  faithfulness: number | null
  relevancy: number
  citation_validity: number
  confidence: number
}

export interface RoutingInfo {
  primary_model: string
  model_used: string
  fell_back: boolean
  latency_ms: number
}

export interface ReportResponse {
  id: string
  session_id: string
  document_id: string | null
  mode: ChatMode
  query: string
  answer: string
  citations: ChatCitation[]
  agent_steps: AgentStep[]
  cache_hit: boolean
  quality: QualityReport
  routing: RoutingInfo | null
  council_run_id: string | null
}

// ---- Council ----

export interface CouncilMemberAnswer {
  model: string
  label: string
  answer: string
  latency_ms: number
}

export interface CouncilPeerReview {
  reviewer_model: string
  scores: Record<string, number>
}

export interface CouncilRunResponse {
  id: string
  session_id: string
  query: string
  members: string[]
  chairman_model: string
  member_answers: CouncilMemberAnswer[]
  peer_reviews: CouncilPeerReview[]
  agreement_score: number
  final_answer: string
}

// ---- Profiler / Advisor ----

export interface ProfileResponse {
  document_id: string
  pages_estimated: number
  tokens: number
  language: string | null
  heading_density: number
  table_ratio: number
  list_ratio: number
  code_ratio: number
  avg_sentence_length: number
  avg_paragraph_length: number
  duplication_ratio: number
  ocr_confidence: number | null
  entity_density: number
  relation_density: number
  document_type: string
}

export interface CandidateResultOut {
  name: string
  chunking_strategy: string
  chunking_kwargs: Record<string, unknown>
  rerank: boolean
  llm_model: string | null
  retrieval_metrics: Record<string, number>
  faithfulness: number
  avg_latency_ms: number
  index_size: number
  composite_score: number
}

export interface AdvisorResponse {
  document_id: string
  baseline: CandidateResultOut
  suggested: CandidateResultOut
  gain_ndcg_points: number
  rationale: string[]
  suggested_mode: string
  mode_reason: string
  decision: 'accept' | 'ignore' | null
}

// ---- Evaluation ----

export interface GenerateDatasetResponse {
  dataset_id: string
  document_id: string
  version: number
  item_count: number
  categories: Record<string, number>
}

export interface ConfigResultOut {
  name: string
  retrieval_metrics: Record<string, number>
  faithfulness: number
  correctness: number
  citation_validity: number
  p50_latency_ms: number
  p95_latency_ms: number
  n_samples: number
  production_score: number
  passes_hard_gates: boolean
}

export interface BenchmarkRunResponse {
  id: string
  document_id: string
  config_results: ConfigResultOut[]
  injection_block_rate: number
  pii_leak_count: number
  recommended_config: string | null
}

// ---- Audit ----

export interface AuditEntry {
  id: number
  trace_id: string
  session_id: string
  layer: string
  rule: string
  score: number | null
  decision: string
  redacted_excerpt: string | null
  created_at: string
}

export interface AuditListResponse {
  entries: AuditEntry[]
}

// ---- Red-team ----

export interface RedTeamCategoryResult {
  total: number
  blocked: number
  block_rate: number
}

export interface RedTeamRunResponse {
  total_attacks: number
  blocked_attacks: number
  block_rate: number
  total_benign: number
  false_positives: number
  false_positive_rate: number
  by_category: Record<string, RedTeamCategoryResult>
}

// ---- Trace (WS) ----

export type TraceStatus = 'queued' | 'running' | 'done' | 'blocked' | 'error' | 'retrying'

export interface TraceEvent {
  trace_id: string
  session_id: string
  /** Strictly increasing per session_id, assigned server-side (app/core/tracing.py's
   * TraceBus.publish) — the ordering/de-dup key. UI state must be a pure function of events
   * sorted and deduplicated by this, never of arrival order, so replay/scrubbing is
   * deterministic and a reconnect that re-sends history can't double-apply anything. */
  seq: number
  stage: string
  status: TraceStatus
  started_at: string
  duration_ms: number | null
  from_stage: string | null
  to_stage: string | null
  input_preview: string | null
  output_preview: string | null
  metrics: Record<string, unknown>
}
