/** Builds what the canvas draws for each view from the one graph payload. */
import type { ArchitectureEdge, ArchitectureGraph, ArchitectureNode, EdgeKind, NodeStatus } from '@/lib/api/types'
import { edgePath, layoutGraph, type EdgePath, type LaneBand, type Rect } from './layout'

export type ViewMode = 'overview' | 'detailed' | 'live'

export interface StageSummary {
  stage: number | null
  label: string
  description: string
  modules: ArchitectureNode[]
  worst: NodeStatus
  invocations: number
}

export interface SceneNode {
  id: string
  kind: 'module' | 'child' | 'cluster' | 'stage'
  rect: Rect
  parentId?: string
  relative?: { x: number; y: number }
  order: number
  node?: ArchitectureNode
  summary?: StageSummary
  childCount?: number
}

export interface SceneEdge {
  id: string
  source: string
  target: string
  kind: EdgeKind
  label: string
  path: EdgePath
  /** Entrance order of the source node, so the edge draws after its source lands. */
  sourceOrder: number
  count: number
  /** True when the edge crosses more than one lane: drawn fainter so near links read first. */
  far: boolean
}

export interface Scene {
  nodes: SceneNode[]
  edges: SceneEdge[]
  lanes: LaneBand[]
  width: number
  height: number
  /** Real edge id -> the scene edge that represents it in this view (absent if hidden). */
  edgeFor: Record<string, string>
  /** Real node id -> the scene node that represents it in this view. */
  nodeFor: Record<string, string>
}

const SEVERITY: NodeStatus[] = ['healthy', 'not_configured', 'disabled', 'degraded', 'down']

export function worstStatus(statuses: NodeStatus[]): NodeStatus {
  return statuses.reduce<NodeStatus>((worst, s) => (SEVERITY.indexOf(s) > SEVERITY.indexOf(worst) ? s : worst), 'healthy')
}

const STAGE_W = 264
const STAGE_H = 328
const STAGE_GAP = 64

function overviewScene(graph: ArchitectureGraph): Scene {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  // A group's members are summarised with the group, whatever their own stage.
  const stageOf = (node: ArchitectureNode): number | null => {
    const owner = node.parent ? (byId.get(node.parent) ?? node) : node
    return graph.stages.some((s) => s.id === owner.stage) ? owner.stage : null
  }
  const stageKeys: (number | null)[] = graph.stages.map((s) => s.id)
  if (graph.nodes.some((n) => stageOf(n) === null)) stageKeys.push(null)

  const nodes: SceneNode[] = stageKeys.map((stage, i) => {
    const meta = graph.stages.find((s) => s.id === stage)
    const modules = graph.nodes.filter((n) => stageOf(n) === stage)
    return {
      id: `stage:${stage ?? 'none'}`,
      kind: 'stage',
      rect: { x: i * (STAGE_W + STAGE_GAP), y: 0, width: STAGE_W, height: STAGE_H },
      order: i,
      summary: {
        stage,
        label: meta?.label ?? 'Not placed yet',
        description: meta?.description ?? 'Modules that exist in code but have no stage assigned.',
        modules,
        worst: worstStatus(modules.map((m) => m.status).filter((s) => s !== 'not_configured' && s !== 'disabled')),
        invocations: modules.reduce((sum, m) => sum + m.invocation_count, 0),
      },
    }
  })
  const rectOf = new Map(nodes.map((n) => [n.id, n.rect]))
  const sceneIdOf = (id: string) => {
    const node = graph.nodes.find((n) => n.id === id)
    return node ? `stage:${stageOf(node) ?? 'none'}` : undefined
  }

  const merged = new Map<string, SceneEdge>()
  const edgeFor: Record<string, string> = {}
  for (const edge of graph.edges) {
    const source = sceneIdOf(edge.source)
    const target = sceneIdOf(edge.target)
    if (!source || !target || source === target) continue
    const id = `${source}->${target}`
    edgeFor[edge.id] = id
    const existing = merged.get(id)
    if (existing) {
      existing.count += 1
      if (existing.kind !== edge.kind && edge.kind === 'request') existing.kind = 'request'
      continue
    }
    merged.set(id, {
      id,
      source,
      target,
      kind: edge.kind,
      label: '',
      path: edgePath(rectOf.get(source)!, rectOf.get(target)!),
      sourceOrder: nodes.find((n) => n.id === source)!.order,
      count: 1,
      far: false,
    })
  }
  const edges = [...merged.values()].map((e) => ({ ...e, label: `${e.count} connection${e.count === 1 ? '' : 's'}` }))
  const nodeFor: Record<string, string> = {}
  for (const n of graph.nodes) nodeFor[n.id] = sceneIdOf(n.id)!
  return {
    nodes,
    edges,
    lanes: [],
    width: nodes.length * (STAGE_W + STAGE_GAP) - STAGE_GAP,
    height: STAGE_H,
    edgeFor,
    nodeFor,
  }
}

export function buildScene(graph: ArchitectureGraph, view: ViewMode): Scene {
  if (view === 'overview') return overviewScene(graph)

  const layout = layoutGraph(graph, { showConfig: view === 'detailed' })
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const nodes: SceneNode[] = Object.values(layout.nodes).map((placed) => ({
    id: placed.id,
    kind: placed.kind === 'group' ? 'cluster' : placed.kind,
    rect: { x: placed.x, y: placed.y, width: placed.width, height: placed.height },
    parentId: placed.kind === 'child' ? byId.get(placed.id)?.parent ?? undefined : undefined,
    relative: placed.relative,
    order: placed.order,
    node: byId.get(placed.id),
    childCount: placed.kind === 'group' ? graph.nodes.filter((n) => n.parent === placed.id).length : undefined,
  }))
  const rectOf = (id: string) => layout.nodes[id]
  const laneIndex = (y: number) => layout.lanes.findIndex((lane) => y >= lane.y && y < lane.y + lane.height)
  const edges: SceneEdge[] = graph.edges
    .filter((e: ArchitectureEdge) => rectOf(e.source) && rectOf(e.target))
    .map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      kind: e.kind,
      label: e.label,
      path: edgePath(rectOf(e.source), rectOf(e.target)),
      sourceOrder: rectOf(e.source).order,
      count: 1,
      far: Math.abs(laneIndex(rectOf(e.source).y) - laneIndex(rectOf(e.target).y)) > 1,
    }))
  return {
    nodes,
    edges,
    lanes: layout.lanes,
    width: layout.width,
    height: layout.height,
    edgeFor: Object.fromEntries(edges.map((e) => [e.id, e.id])),
    nodeFor: Object.fromEntries(nodes.map((n) => [n.id, n.id])),
  }
}
