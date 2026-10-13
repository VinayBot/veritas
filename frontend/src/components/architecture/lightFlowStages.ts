/** LF-2/LF-3/LF-4: the five light-flow stages. Edge ids reference EDGE_LAYOUT in
 * architectureLayout.ts — every id here must exist there (checked by the contract test).
 * Stage 1's path follows the real backend (gateway -> ingest_scheduler directly; uploads
 * never touch the chat mode router or guardrails_in, which only run on chat turns) rather
 * than the brief's own illustrative sequence, per AR-5's "follow the real backend where it
 * differs." */

export interface LightFlowStage {
  id: 1 | 2 | 3 | 4 | 5
  name: string
  description: string
  color: string
  /** Edge ids walked in order; the comet travels edge[i] then edge[i+1], etc. */
  edgeIds: string[]
}

export const LIGHT_FLOW_STAGES: LightFlowStage[] = [
  {
    id: 1,
    name: 'Upload & Deliver',
    description: 'A document reaches the gateway and is handed to the ingestion scheduler and its parser/scraper workers.',
    color: '#22D3EE',
    edgeIds: [
      'user-gateway',
      'gateway-ingest_scheduler',
      'event_bus-ingest_scheduler',
      'ingest_scheduler-worker_docling',
    ],
  },
  {
    id: 2,
    name: 'Refine & Protect',
    description: 'Parsed text is refined and PII-masked before anything is written to storage.',
    color: '#A78BFA',
    edgeIds: ['worker_docling-pii_vault', 'metadb-pii_vault'],
  },
  {
    id: 3,
    name: 'Understand',
    description: 'Chunking, embedding, BM25 indexing and graph extraction build the three retrieval indexes.',
    color: '#34D399',
    edgeIds: [
      'worker_refiner-index_manager',
      'index_manager-index_dense',
      'index_manager-index_sparse',
      'index_manager-index_graph',
    ],
  },
  {
    id: 4,
    name: 'Retrieve & Reason',
    description: 'A chat turn is guarded, routed, and reasoned over by the orchestrator against the indexes and LLM providers.',
    color: '#FBBF24',
    edgeIds: [
      'user-gateway',
      'gateway-guardrails_in',
      'gateway-router',
      'router-orchestrator',
      'orchestrator-index_manager',
      'orchestrator-llm_providers',
    ],
  },
  {
    id: 5,
    name: 'Answer & Celebrate',
    description: 'The verified answer is published to the trace bus and streamed back to the user.',
    color: '#F472B6',
    edgeIds: ['orchestrator-event_bus', 'event_bus-user'],
  },
]
