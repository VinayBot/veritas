/**
 * Hand-authored System Design layout (AR-2): every node's (x, y) center on a 1600x1000
 * logical canvas, and every edge's explicit orthogonal waypoints. No auto-layout engine reads
 * or arranges this — positions below are placed by hand to match the brief's reference
 * image's proportions (spine at ~57% height, branches above/below, group boxes top-right and
 * bottom-right). The one helper function here (`elbow`) only turns two fixed, hand-placed
 * points into a 90°-cornered connector path — the same thing a human draws with a diagramming
 * tool's "orthogonal connector", not a force-directed/constraint-solving layout algorithm.
 */

export const CANVAS_WIDTH = 1600
export const CANVAS_HEIGHT = 1000
const SPINE_Y = 570

export interface NodeLayout {
  x: number
  y: number
  /** Icon box size in px (not the group box). */
  size: number
}

export const NODE_LAYOUT: Record<string, NodeLayout> = {
  user: { x: 90, y: SPINE_Y, size: 64 },
  gateway: { x: 330, y: SPINE_Y, size: 60 },
  router: { x: 650, y: SPINE_Y, size: 60 },
  orchestrator: { x: 970, y: SPINE_Y, size: 64 },
  event_bus: { x: 1290, y: SPINE_Y, size: 60 },

  guardrails_in: { x: 330, y: 360, size: 56 },
  trace_ids: { x: 1090, y: 330, size: 52 },
  llm_providers: { x: 150, y: 160, size: 60 },

  metadb: { x: 760, y: 760, size: 56 },
  cache: { x: 760, y: 900, size: 52 },
  pii_vault: { x: 1030, y: 820, size: 56 },
  index_manager: { x: 970, y: 760, size: 56 },
  ingest_scheduler: { x: 1290, y: 760, size: 56 },
  evaluator: { x: 150, y: 870, size: 56 },

  index_dense: { x: 1430, y: 185, size: 48 },
  index_sparse: { x: 1430, y: 265, size: 48 },
  index_graph: { x: 1430, y: 345, size: 48 },

  council_member_1: { x: 1430, y: 440, size: 48 },
  council_member_2: { x: 1430, y: 510, size: 48 },
  council_chairman: { x: 1430, y: 580, size: 48 },

  worker_docling: { x: 1430, y: 700, size: 48 },
  worker_scraper: { x: 1430, y: 775, size: 48 },
  worker_refiner: { x: 1430, y: 850, size: 48 },
}

export interface GroupBoxLayout {
  id: 'indexes' | 'council' | 'workers'
  title: string
  x: number
  y: number
  width: number
  height: number
}

export const GROUP_BOXES: GroupBoxLayout[] = [
  { id: 'indexes', title: 'Shards', x: 1340, y: 130, width: 180, height: 260 },
  { id: 'council', title: 'Replicas', x: 1340, y: 400, height: 210, width: 180 },
  { id: 'workers', title: 'Workers', x: 1340, y: 650, width: 180, height: 230 },
]

export type EdgeDirection = 'bidirectional' | 'forward' | 'backward'

export interface EdgeLayout {
  id: string
  source: string
  target: string
  direction: EdgeDirection
  label?: string
  /** Explicit orthogonal waypoints, source anchor to target anchor, 90° corners only. */
  points: { x: number; y: number }[]
}

function node(id: string): NodeLayout {
  const n = NODE_LAYOUT[id]
  if (!n) throw new Error(`architectureLayout: no NODE_LAYOUT entry for "${id}"`)
  return n
}

/** Two fixed points -> an orthogonal (90°-cornered) connector. `bend` picks whether the
 * single corner sits at the source's x or the target's x — hand-chosen per edge below to
 * avoid crossing a node, not computed by any collision-avoidance search. */
function elbow(aId: string, bId: string, bend: 'at-source-x' | 'at-target-x' | 'at-mid-y' = 'at-source-x') {
  const a = node(aId)
  const b = node(bId)
  if (a.y === b.y) return [{ x: a.x, y: a.y }, { x: b.x, y: b.y }]
  if (bend === 'at-mid-y') {
    const midY = (a.y + b.y) / 2
    return [
      { x: a.x, y: a.y },
      { x: a.x, y: midY },
      { x: b.x, y: midY },
      { x: b.x, y: b.y },
    ]
  }
  const cornerX = bend === 'at-source-x' ? a.x : b.x
  return [
    { x: a.x, y: a.y },
    { x: cornerX, y: a.y },
    { x: cornerX, y: b.y },
    { x: b.x, y: b.y },
  ]
}

function groupMemberEdge(managerId: string, memberId: string): { x: number; y: number }[] {
  const m = node(managerId)
  const n = node(memberId)
  return [
    { x: m.x, y: m.y },
    { x: n.x - 80, y: m.y },
    { x: n.x - 80, y: n.y },
    { x: n.x, y: n.y },
  ]
}

export const EDGE_LAYOUT: EdgeLayout[] = [
  { id: 'user-gateway', source: 'user', target: 'gateway', direction: 'bidirectional', points: elbow('user', 'gateway') },
  { id: 'gateway-guardrails_in', source: 'gateway', target: 'guardrails_in', direction: 'bidirectional', points: elbow('gateway', 'guardrails_in') },
  { id: 'gateway-router', source: 'gateway', target: 'router', direction: 'bidirectional', points: elbow('gateway', 'router') },
  {
    id: 'gateway-ingest_scheduler',
    source: 'gateway',
    target: 'ingest_scheduler',
    direction: 'bidirectional',
    points: [
      { x: node('gateway').x, y: node('gateway').y },
      { x: node('gateway').x, y: 820 },
      { x: node('ingest_scheduler').x, y: 820 },
      { x: node('ingest_scheduler').x, y: node('ingest_scheduler').y },
    ],
  },
  { id: 'router-orchestrator', source: 'router', target: 'orchestrator', direction: 'bidirectional', points: elbow('router', 'orchestrator') },
  { id: 'orchestrator-event_bus', source: 'orchestrator', target: 'event_bus', direction: 'bidirectional', points: elbow('orchestrator', 'event_bus') },
  {
    id: 'event_bus-user',
    source: 'event_bus',
    target: 'user',
    direction: 'forward',
    label: 'Notifications',
    points: [
      { x: node('event_bus').x, y: node('event_bus').y + 180 },
      { x: node('user').x, y: node('event_bus').y + 180 },
      { x: node('user').x, y: node('user').y + 40 },
    ],
  },
  {
    id: 'orchestrator-llm_providers',
    source: 'orchestrator',
    target: 'llm_providers',
    direction: 'bidirectional',
    points: [
      { x: node('orchestrator').x, y: node('orchestrator').y },
      { x: node('orchestrator').x, y: 160 },
      { x: node('llm_providers').x, y: 160 },
    ],
  },
  { id: 'orchestrator-index_manager', source: 'orchestrator', target: 'index_manager', direction: 'bidirectional', points: elbow('orchestrator', 'index_manager') },
  { id: 'index_manager-index_dense', source: 'index_manager', target: 'index_dense', direction: 'bidirectional', points: groupMemberEdge('index_manager', 'index_dense') },
  { id: 'index_manager-index_sparse', source: 'index_manager', target: 'index_sparse', direction: 'bidirectional', points: groupMemberEdge('index_manager', 'index_sparse') },
  { id: 'index_manager-index_graph', source: 'index_manager', target: 'index_graph', direction: 'bidirectional', points: groupMemberEdge('index_manager', 'index_graph') },
  { id: 'orchestrator-council_member_1', source: 'orchestrator', target: 'council_member_1', direction: 'bidirectional', points: groupMemberEdge('orchestrator', 'council_member_1') },
  { id: 'orchestrator-council_member_2', source: 'orchestrator', target: 'council_member_2', direction: 'bidirectional', points: groupMemberEdge('orchestrator', 'council_member_2') },
  { id: 'orchestrator-council_chairman', source: 'orchestrator', target: 'council_chairman', direction: 'bidirectional', points: groupMemberEdge('orchestrator', 'council_chairman') },
  { id: 'orchestrator-metadb', source: 'orchestrator', target: 'metadb', direction: 'bidirectional', points: elbow('orchestrator', 'metadb', 'at-target-x') },
  { id: 'metadb-cache', source: 'metadb', target: 'cache', direction: 'bidirectional', points: elbow('metadb', 'cache') },
  { id: 'metadb-pii_vault', source: 'metadb', target: 'pii_vault', direction: 'bidirectional', points: elbow('metadb', 'pii_vault', 'at-mid-y') },
  { id: 'pii_vault-event_bus', source: 'pii_vault', target: 'event_bus', direction: 'bidirectional', points: elbow('pii_vault', 'event_bus', 'at-target-x') },
  { id: 'orchestrator-trace_ids', source: 'orchestrator', target: 'trace_ids', direction: 'bidirectional', points: elbow('orchestrator', 'trace_ids') },
  { id: 'event_bus-ingest_scheduler', source: 'event_bus', target: 'ingest_scheduler', direction: 'bidirectional', points: elbow('event_bus', 'ingest_scheduler') },
  { id: 'ingest_scheduler-worker_docling', source: 'ingest_scheduler', target: 'worker_docling', direction: 'bidirectional', points: groupMemberEdge('ingest_scheduler', 'worker_docling') },
  { id: 'ingest_scheduler-worker_scraper', source: 'ingest_scheduler', target: 'worker_scraper', direction: 'bidirectional', points: groupMemberEdge('ingest_scheduler', 'worker_scraper') },
  { id: 'ingest_scheduler-worker_refiner', source: 'ingest_scheduler', target: 'worker_refiner', direction: 'bidirectional', points: groupMemberEdge('ingest_scheduler', 'worker_refiner') },
  {
    id: 'worker_docling-pii_vault',
    source: 'worker_docling',
    target: 'pii_vault',
    direction: 'forward',
    points: elbow('worker_docling', 'pii_vault', 'at-mid-y'),
  },
  {
    id: 'worker_refiner-index_manager',
    source: 'worker_refiner',
    target: 'index_manager',
    direction: 'forward',
    points: elbow('worker_refiner', 'index_manager', 'at-mid-y'),
  },
  { id: 'evaluator-orchestrator', source: 'evaluator', target: 'orchestrator', direction: 'bidirectional', points: elbow('evaluator', 'orchestrator', 'at-mid-y') },
  { id: 'evaluator-ingest_scheduler', source: 'evaluator', target: 'ingest_scheduler', direction: 'bidirectional', points: elbow('evaluator', 'ingest_scheduler', 'at-source-x') },
]

export const EDGE_LAYOUT_BY_ID: Record<string, EdgeLayout> = Object.fromEntries(
  EDGE_LAYOUT.map((e) => [e.id, e]),
)
