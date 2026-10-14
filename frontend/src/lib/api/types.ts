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
  /** The strategy this document is answered with: measured best after upload, or the user's choice. */
  preferred_strategy?: string | null
  strategy_source?: 'measured' | 'chosen' | null
  measure_status?: 'queued' | 'running' | 'done' | 'skipped' | 'failed' | null
  measure_error?: string | null
  created_at: string
  updated_at: string
}

export interface DocumentSummary {
  id: string
  filename: string
  source_type: string
  status: DocumentStatus
  enrichment_status: EnrichmentStatus
  chunk_count: number | null
  chunk_strategy: string | null
  graph_entity_count: number | null
  created_at: string
  updated_at: string
}

export interface DocumentListResponse {
  documents: DocumentSummary[]
  /** Every document matching the filter, not just the page returned. */
  total: number
}

export interface DeleteDocumentResponse {
  document_id: string
  chunks_removed: number
  graph_edges_removed: number
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

// ---- Architecture ----

export type NodeStatus = 'healthy' | 'degraded' | 'down' | 'disabled' | 'not_configured'
export type EdgeKind = 'request' | 'data' | 'trace' | 'optional'

export interface ArchitectureStage {
  id: number
  label: string
  description: string
}

export interface ArchitectureNode {
  id: string
  label: string
  module_path: string
  one_line_purpose: string
  stage: number | null
  parent: string | null
  documented: boolean
  status: NodeStatus
  status_detail: string
  /** What kind of check backs `status`; "import" is the weakest. */
  probe_kind: string
  probe_id: string | null
  trace_stages: string[]
  invocation_count: number
  error_count: number
  last_latency_ms: number | null
  last_at: string | null
  p50_latency_ms: number | null
  p95_latency_ms: number | null
  latency_sample_size: number
  config: Record<string, unknown>
  source_path: string
  source_abs_path: string
}

export interface ArchitectureEdge {
  id: string
  source: string
  target: string
  kind: EdgeKind
  label: string
  derived: 'langgraph' | 'declared'
}

export interface ArchitectureGraph {
  generated_at: string
  stats_since: string
  stages: ArchitectureStage[]
  nodes: ArchitectureNode[]
  edges: ArchitectureEdge[]
  stage_to_node: Record<string, string>
}

export interface NodeEventsResponse {
  node_id: string
  events: TraceEvent[]
}

// ---- Health ----

export interface Subsystem {
  id: string
  label: string
  status: NodeStatus
  detail: string
  kind: string
  raw: Record<string, unknown>
  error: string | null
  fix: string | null
  latency_ms: number
  p50_latency_ms: number | null
  checked_at: string
}

export interface SubsystemsResponse {
  checked_at: string
  subsystems: Subsystem[]
}

export interface SelfCheckStage {
  name: string
  label: string
  ok: boolean
  duration_ms: number
  detail: string
  error: string | null
}

export interface SelfCheckResponse {
  ok: boolean
  total_ms: number
  ran_at: string
  stages: SelfCheckStage[]
}

// ---- Chat ----

export type AnswerDetail = 'brief' | 'deep'

export interface ChatCitation {
  marker: number
  chunk_id: string
  text: string
}

export interface AgentStep {
  node: string
  summary: string
}

export interface GroundingReport {
  score: number
  sentences: { text: string; supported: boolean }[]
  supported: number
  total: number
}

/** Every score is null when it could not be measured; nothing is filled in. */
export interface QualityReport {
  label: string
  faithfulness: number | null
  relevancy: number | null
  citation_validity: number | null
  grounding: GroundingReport | null
  confidence: number | null
  judge_model: string | null
  not_measured_reason?: string | null
}

export interface RoutingInfo {
  primary_model: string
  model_used: string
  fell_back: boolean
  latency_ms: number
}

export interface RetrievedChunk {
  position: number
  chunk_id: string
  text: string
  score: number | null
  source: string | null
  /** "dense" | "sparse" | "both" | "graph" | "both+graph" ... */
  found_by: string | null
  dense_rank: number | null
  sparse_rank: number | null
  rerank_score: number | null
  section_path: string | null
  /** Null for every document today: no parser records page numbers. */
  page: number | null
  chunking: string | null
  used: boolean
  citation_marker: number | null
  flagged_injection: boolean
}

export interface RetrievalFunnel {
  searches: number
  dense_candidates: number | null
  sparse_candidates: number | null
  after_fusion: number | null
  after_rerank: number | null
  returned: number | null
  in_context: number
  used_in_answer: number
}

export interface StageTiming {
  stage: string
  status: string
  started_at: string
  duration_ms: number | null
  input_preview: string | null
  output_preview: string | null
  metrics: Record<string, unknown>
}

export interface TokenUsage {
  llm_calls: number
  prompt_tokens: number
  completion_tokens: number
  by_model: Record<string, { calls: number; prompt_tokens: number; completion_tokens: number }>
  calls_without_usage?: number
  models?: { generator: string; judge: string; embedding: string; reranker: string }
}

export interface ReportResponse {
  id: string
  session_id: string
  document_id: string | null
  strategy: string
  detail: AnswerDetail | null
  outcome: string | null
  query: string
  answer: string
  citations: ChatCitation[]
  agent_steps: AgentStep[]
  cache_hit: boolean
  quality: QualityReport
  routing: RoutingInfo | null
  council_run_id: string | null
  latency_ms: number | null
  usage: TokenUsage | null
  retrieval: { funnel: RetrievalFunnel | null; chunks: RetrievedChunk[] } | null
  timings: StageTiming[] | null
  loops: Record<string, number> | null
  created_at: string
}

export interface AnswerSummary {
  strategy: string
  detail: AnswerDetail
  latency_ms: number
  cache_hit: boolean
  outcome: string
  usage: TokenUsage | null
}

// ---- RAG strategies ----

export interface Strategy {
  id: string
  display_name: string
  description: string
  best_for: string
  components: string[]
  kind: 'direct' | 'agentic'
  typical_latency_ms: number
  measured_latency_ms: number | null
  measured_runs: number
  relative_cost: 'low' | 'medium' | 'high' | 'very_high'
  min_hardware_tier: string
  suited_for: string[]
  llm_calls: number
  available: boolean
  unavailable_reason: string | null
  action: 'build_index' | 'build_graph' | null
  warning: string | null
  is_default: boolean
}

export interface StrategiesResponse {
  default: string
  document_id: string | null
  strategies: Strategy[]
}

export interface Recommendation {
  document_id: string
  recommended: string
  display_name: string
  confidence: number
  reasons: string[]
  runner_up: string | null
  runner_up_display_name: string | null
  not_recommended: { id: string; why: string }[]
  scores: Record<string, number>
  rule_trace: { rule: string; description: string; fired: boolean; effects: Record<string, number> }[]
  available: boolean
  unavailable_reason: string | null
  action: 'build_index' | 'build_graph' | null
  current_default: string
  provisional: boolean
  features: ProfileResponse
  /** "measured": follows strategies run on this document's question set. "rules": a
   * prediction from the document's shape that has not been checked yet. */
  basis: 'measured' | 'rules'
  measured: MeasuredEvidence | null
  rule_recommended: string
  rule_display_name: string
  rule_reasons: string[]
  /** Where current_default comes from for this document. */
  strategy_source: 'measured' | 'chosen' | 'default'
  measure_status: 'queued' | 'running' | 'done' | 'skipped' | 'failed' | null
  measure_error: string | null
  /** A measurement starts by itself after upload. */
  auto_measure: boolean
}

export interface MeasuredEvidence {
  source: 'comparison' | 'evaluation'
  run_id: string
  created_at: string | null
  n: number
  small_sample: boolean
  metrics_used: string[]
  ranking: { strategy: string; display_name: string; score: number }[]
  winner: string
  margin: number
  clear: boolean
  measured: string[]
}

export interface MetricDelta {
  baseline: number
  value: number
  delta: number
  points?: number
  n: number
  small_sample: boolean
}

export interface ComparisonResult {
  document_id: string
  dataset: { id: string; version: number; item_count: number } | null
  query: string | null
  baseline: string
  strategies: (ConfigResultOut & { cached: boolean; evaluated_at?: string })[]
  deltas: Record<string, Record<string, MetricDelta>>
  winner: {
    id: string
    is_baseline: boolean
    margin: number
    scores: Record<string, number>
    metrics_used: string[]
    n: number
    reason: string
  } | null
  n_queries: number
  small_sample: boolean
  small_sample_note: string | null
  run_config: Record<string, string | null>
  ran: string[]
  duration_ms: number
}

export interface Comparison {
  id: string
  document_id: string
  created_at: string
  result: ComparisonResult
}

export interface CompareEstimate {
  document_id: string
  dataset: { id: string; version: number; item_count: number } | null
  query: string | null
  strategies: {
    strategy: string
    questions: number
    cached: boolean
    latency_per_question_s: number
    latency_source: string
    estimated_seconds: number
    llm_calls: number
  }[]
  questions: number
  total_llm_calls: number
  estimated_seconds: number
  concurrency: number
  all_cached: boolean
}

// ---- Jobs ----

export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface Job {
  id: string
  kind: string
  status: JobStatus
  params: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
  progress: number
  message: string | null
  created_at: string
  updated_at: string
}

// ---- Models ----

export interface ModelRoles {
  generator: boolean
  council_member: boolean
  judge: boolean
  embedder: boolean
  guard: boolean
  notes: string[]
}

export interface ChatModel {
  id: string
  name: string
  provider: string
  cloud: boolean
  family?: string | null
  parameter_size?: string | null
  quantization?: string | null
  context_length?: number | null
  disk_bytes: number | null
  loaded: boolean
  vram_bytes: number | null
  roles: ModelRoles
}

export interface HfModel {
  id: string
  name: string
  provider: string
  downloaded: boolean
  loaded: boolean
  disk_bytes: number | null
}

export interface ModelSelection {
  generator: string
  judge: string
  council: string[]
  chairman: string
  embedding: string
  reranker: string
  guard: string
}

export interface IndexStatus {
  active_embedding_model: string
  ready_documents: number
  stale_count: number
  stale_chunks: number
  stale_documents: { id: string; filename: string; embedding_model: string; chunk_count: number | null; stale: boolean }[]
}

export interface ModelsState {
  ollama: { status: 'up' | 'down'; error: string | null; fix: string | null; base_url: string }
  chat_models: ChatModel[]
  embedding_models: HfModel[]
  reranker_models: HfModel[]
  selection: ModelSelection
  budget: {
    tier: string
    budget_bytes: number
    selected_bytes: number
    basis: string
    over_budget: boolean
    warning: string | null
  }
  index: IndexStatus
}

// ---- Analytics ----

export interface DayPoint {
  date: string
  queries: number
  faithfulness: number | null
  faithfulness_n: number
  grounding: number | null
  grounding_n: number
  relevancy: number | null
  zero_citation_rate: number | null
  avg_citations: number | null
}

export interface AnalyticsOverview {
  window_days: number
  generated_at: string
  corpus: {
    documents: number
    documents_by_status: Record<string, number>
    chunks: number
    variant_chunks: number
    tokens: number
    index_bytes: { vectors: number; database: number; graph: number }
    embedding_model: string
    last_ingest: { filename: string; at: string } | null
  }
  queries: {
    in_window: number
    all_time: number
    cache_hits: number
    by_day: DayPoint[]
    latency_ms: { p50: number | null; p95: number | null; n: number }
    latency_by_strategy: { strategy: string; display_name: string; p50: number | null; p95: number | null; n: number }[]
    latency_by_stage: { stage: string; p50: number | null; p95: number | null; n: number }[]
    reports_with_stage_timings: number
    avg_tokens_per_answer: number | null
    reports_with_token_counts: number
    strategy_mix: { strategy: string; display_name: string; count: number; share: number }[]
  }
  reliability: {
    runs: number
    failed: number
    cancelled: number
    blocked: number
    abstained: number
    retried_after_timeout: number
    failure_rate: number | null
    retry_rate: number | null
    critic_retry_turns: number
    revision_turns: number
    turns_with_loop_data: number
    agent_retry_rate: number | null
  }
  quality: {
    faithfulness: number | null
    grounding: number | null
    relevancy: number | null
    zero_citation_rate: number | null
    zero_citation_answers: number
    answered: number
    avg_citations: number | null
  }
  guardrails: AuditSummaryResponse
}

export interface GraphStats {
  document_id: string | null
  entities: number
  relations: number
  communities: number
  orphans: number
  orphan_rate: number | null
  largest_communities: { id: number; size: number; top_entities: string[] }[]
  most_connected: { id: string; name: string; label: string; degree: number; doc_ids: string[] }[]
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
  tokens: number
  characters: number
  page_count: number | null
  pages_estimated: number
  language: string | null
  heading_density: number
  table_ratio: number
  list_ratio: number
  code_ratio: number
  content_class: string
  avg_sentence_length: number
  avg_paragraph_length: number
  duplication_ratio: number
  lexical_diversity: number
  ocr_confidence: number | null
  low_quality_scan: boolean
  entity_density: number
  unique_entity_density: number
  unique_entities: number
  entity_types: number
  entity_type_spread: number
  entities_fully_scanned: boolean
  relation_density: number
  cross_references: number
  cross_reference_density: number
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
  n_samples: number
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
  /** Every tournament candidate, not just baseline/winner — one per chunking strategy once
   * default_candidates() covers all 6 (see backend/app/profiler/tournament.py). */
  candidates: CandidateResultOut[]
}

// ---- Evaluation ----

export interface GenerateDatasetResponse {
  dataset_id: string
  document_id: string
  version: number
  item_count: number
  categories: Record<string, number>
}

export interface EvalSample {
  item_id: string
  category: string
  question: string
  reference_answer: string | null
  answer: string
  outcome: string
  citations: number
  latency_ms: number
  faithfulness: number | null
  relevancy: number | null
  correctness: number | null
  citation_validity: number | null
}

export interface ConfigResultOut {
  name: string
  retrieval_metrics: Record<string, number>
  /** null = not measured. */
  faithfulness: number | null
  answer_relevancy: number | null
  correctness: number | null
  citation_validity: number | null
  p50_latency_ms: number
  p95_latency_ms: number
  n_samples: number
  n_judged: Record<string, number>
  avg_prompt_tokens: number | null
  avg_completion_tokens: number | null
  avg_llm_calls: number | null
  production_score: number | null
  passes_hard_gates: boolean
  gate_failures: string[]
  skipped_reason: string | null
  samples: EvalSample[]
}

export interface BenchmarkRunResponse {
  id: string
  document_id: string
  created_at: string
  config_results: ConfigResultOut[]
  injection_block_rate: number | null
  pii_leak_count: number | null
  recommended_config: string | null
  /** 2 = current harness. null = a run from the first harness; not comparable with later runs. */
  harness_version: number | null
  dataset_id: string | null
  dataset_version: number | null
  n_items: number | null
  run_config: Record<string, string | null> | null
  duration_ms: number | null
}

export interface BenchmarkRunListResponse {
  runs: BenchmarkRunResponse[]
}

export interface EvalDataset {
  id: string
  document_id: string
  version: number
  item_count: number
  created_at: string
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

export interface AuditRuleSummary {
  layer: string
  rule: string
  total: number
  allow: number
  redact: number
  block: number
  escalate: number
  trip_rate: number
}

/** Real traffic only — red-team and evaluation sessions are excluded server-side. */
export interface AuditSummaryResponse {
  total: number
  by_decision: Record<string, number>
  by_layer: Record<string, number>
  rules: AuditRuleSummary[]
  trip_rate: number | null
  first_at: string | null
  last_at: string | null
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
