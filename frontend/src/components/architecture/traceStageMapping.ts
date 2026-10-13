/** Live mode (LF-3) emits a comet when a real TraceEvent arrives — but TraceEvent.stage names
 * are the real pipeline stage ids (INGESTION_LANE/CHAT_LANE from the old Detailed view, e.g.
 * "parse", "embed", "guardian_in"), not this diagram's node/edge ids. This is the hand-authored
 * mapping from each real stage id to the architecture edge that most faithfully represents it
 * — approximate by nature (several granular pipeline stages collapse onto one diagram edge),
 * logged as an assumption rather than invented silently. Every value must be a real edge id
 * from EDGE_LAYOUT (checked by the contract test). */
export const PIPELINE_STAGE_TO_EDGE: Record<string, string> = {
  // Ingestion critical path
  upload: 'user-gateway',
  parse: 'gateway-ingest_scheduler',
  refine: 'ingest_scheduler-worker_refiner',
  pii_vault: 'worker_docling-pii_vault',
  chunk: 'worker_refiner-index_manager',
  embed: 'index_manager-index_dense',
  index: 'index_manager-index_sparse',
  // Enrichment (non-blocking, after the document is ready for chat)
  graph: 'index_manager-index_graph',
  profile: 'metadb-pii_vault',
  advisor: 'evaluator-orchestrator',
  // Chat pipeline
  guardian_in: 'gateway-guardrails_in',
  semantic_cache: 'metadb-cache',
  planner: 'router-orchestrator',
  rewriter: 'router-orchestrator',
  retriever: 'orchestrator-index_manager',
  critic: 'orchestrator-index_manager',
  synthesizer: 'orchestrator-llm_providers',
  verifier: 'orchestrator-llm_providers',
  guardian_out: 'orchestrator-event_bus',
}
