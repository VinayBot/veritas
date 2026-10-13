/**
 * Deterministic layered layout for the architecture graph. Pure function of the payload:
 * the same nodes and edges always produce the same picture, and a changed topology produces
 * a new one with no stored coordinates anywhere.
 *
 * Detailed layout: one horizontal lane per stage, stacked top to bottom in story order.
 * Inside a lane, nodes are ranked left to right by the longest path over that lane's own
 * edges, and ordered within a rank by the average position of their neighbours
 * (barycentre), which keeps connected nodes near each other. A group (the agent's LangGraph
 * nodes) takes a full row of its lane and is ranked internally the same way.
 */
import type { ArchitectureEdge, ArchitectureGraph, ArchitectureNode } from '@/lib/api/types'

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

export interface LaidOutNode extends Rect {
  id: string
  /** Position along the flow, used to stagger the entrance animation. */
  order: number
  kind: 'module' | 'group' | 'child'
  /** For a child: position relative to its group. */
  relative?: { x: number; y: number }
}

export interface LaneBand extends Rect {
  stage: number | null
  label: string
}

export interface GraphLayout {
  nodes: Record<string, LaidOutNode>
  lanes: LaneBand[]
  width: number
  height: number
}

export const NODE_W = 216
export const CHILD_W = 134
export const CHILD_H = 46
const NODE_BASE_H = 62
const CONFIG_ROW_H = 16
const MAX_CONFIG_ROWS = 3
const GAP_X = 52
const GAP_Y = 14
const CHILD_GAP_X = 22
const CHILD_GAP_Y = 10
const GROUP_PAD = 16
const GROUP_HEADER = 40
const LANE_PAD_Y = 16
const LANE_GAP = 16
export const LANE_LABEL_W = 118
const ROW_GAP = 18

export function nodeHeight(node: ArchitectureNode, showConfig: boolean): number {
  if (!showConfig) return NODE_BASE_H
  const rows = Math.min(Object.keys(node.config).length, MAX_CONFIG_ROWS)
  return NODE_BASE_H + rows * CONFIG_ROW_H + (rows > 0 ? 6 : 0)
}

/** Longest-path rank over a set of edges, ignoring back edges so cycles cannot loop. */
export function rankNodes(ids: string[], edges: { source: string; target: string }[]): Record<string, number> {
  const idSet = new Set(ids)
  const out: Record<string, string[]> = {}
  const indegree: Record<string, number> = {}
  for (const id of ids) {
    out[id] = []
    indegree[id] = 0
  }
  const relevant = edges.filter((e) => idSet.has(e.source) && idSet.has(e.target) && e.source !== e.target)

  // Drop back edges found by a depth-first walk in id order, so the result is a DAG.
  const state: Record<string, 0 | 1 | 2> = {}
  const forward: { source: string; target: string }[] = []
  const adjacency: Record<string, string[]> = {}
  for (const id of ids) adjacency[id] = []
  for (const e of relevant) adjacency[e.source].push(e.target)
  const hasIncoming = new Set(relevant.map((e) => e.target))
  const roots = [...ids.filter((id) => !hasIncoming.has(id)), ...ids]
  const visit = (id: string) => {
    state[id] = 1
    for (const next of adjacency[id]) {
      if (state[next] === 1) continue // back edge
      forward.push({ source: id, target: next })
      if (!state[next]) visit(next)
    }
    state[id] = 2
  }
  for (const id of roots) if (!state[id]) visit(id)

  for (const e of forward) {
    out[e.source].push(e.target)
    indegree[e.target] += 1
  }
  const rank: Record<string, number> = {}
  const queue = ids.filter((id) => indegree[id] === 0)
  for (const id of queue) rank[id] = 0
  while (queue.length > 0) {
    const id = queue.shift()!
    for (const next of out[id]) {
      rank[next] = Math.max(rank[next] ?? 0, rank[id] + 1)
      indegree[next] -= 1
      if (indegree[next] === 0) queue.push(next)
    }
  }
  for (const id of ids) rank[id] ??= 0
  return rank
}

/** Orders nodes inside each rank by the mean index of their neighbours in the previous rank. */
function orderWithinRanks(
  ids: string[],
  rank: Record<string, number>,
  edges: { source: string; target: string }[],
): string[][] {
  const maxRank = Math.max(0, ...ids.map((id) => rank[id]))
  const columns: string[][] = Array.from({ length: maxRank + 1 }, () => [])
  for (const id of [...ids].sort()) columns[rank[id]].push(id)

  const neighbours: Record<string, string[]> = {}
  for (const id of ids) neighbours[id] = []
  for (const e of edges) {
    if (neighbours[e.source] && neighbours[e.target]) {
      neighbours[e.source].push(e.target)
      neighbours[e.target].push(e.source)
    }
  }
  for (let sweep = 0; sweep < 4; sweep += 1) {
    const forwardSweep = sweep % 2 === 0
    const range = forwardSweep ? columns.map((_, i) => i).slice(1) : columns.map((_, i) => i).slice(0, -1).reverse()
    for (const col of range) {
      const reference = columns[forwardSweep ? col - 1 : col + 1]
      const index = new Map(reference.map((id, i) => [id, i]))
      const score = (id: string) => {
        const hits = neighbours[id].filter((n) => index.has(n)).map((n) => index.get(n)!)
        return hits.length === 0 ? Number.POSITIVE_INFINITY : hits.reduce((a, b) => a + b, 0) / hits.length
      }
      columns[col] = [...columns[col]].sort((a, b) => {
        const diff = score(a) - score(b)
        if (Number.isFinite(diff) && diff !== 0) return diff
        if (score(a) !== score(b)) return score(a) === Number.POSITIVE_INFINITY ? 1 : -1
        return a.localeCompare(b)
      })
    }
  }
  return columns
}

interface Block {
  width: number
  height: number
  /** Node rects relative to the block's top-left. */
  placed: Record<string, Rect>
}

function layoutColumns(columns: string[][], size: (id: string) => { width: number; height: number }, gapX: number, gapY: number): Block {
  const placed: Record<string, Rect> = {}
  const columnHeights = columns.map((col) => col.reduce((sum, id) => sum + size(id).height, 0) + Math.max(0, col.length - 1) * gapY)
  const height = Math.max(0, ...columnHeights)
  let x = 0
  columns.forEach((col, i) => {
    const colWidth = Math.max(0, ...col.map((id) => size(id).width))
    let y = (height - columnHeights[i]) / 2
    for (const id of col) {
      const s = size(id)
      placed[id] = { x, y, width: s.width, height: s.height }
      y += s.height + gapY
    }
    if (col.length > 0) x += colWidth + gapX
  })
  return { width: Math.max(0, x - gapX), height, placed }
}

export function layoutGraph(graph: ArchitectureGraph, { showConfig }: { showConfig: boolean }): GraphLayout {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const topLevel = graph.nodes.filter((n) => !n.parent || !byId.has(n.parent))
  const childrenOf = new Map<string, ArchitectureNode[]>()
  for (const n of graph.nodes) {
    if (n.parent && byId.has(n.parent)) {
      childrenOf.set(n.parent, [...(childrenOf.get(n.parent) ?? []), n])
    }
  }
  const topId = (id: string) => {
    const node = byId.get(id)
    return node?.parent && byId.has(node.parent) ? node.parent : id
  }
  const lifted = graph.edges
    .map((e) => ({ source: topId(e.source), target: topId(e.target), kind: e.kind }))
    .filter((e) => e.source !== e.target)

  // Groups: rank the children on the group's own internal edges.
  const groupBlocks = new Map<string, Block>()
  for (const [groupId, children] of childrenOf) {
    const ids = children.map((c) => c.id)
    const internal = graph.edges.filter((e) => ids.includes(e.source) && ids.includes(e.target))
    const rank = rankNodes(ids, internal)
    // Anything the group's entry point feeds sits to its right: the orchestrator's edge
    // into the state machine is declared, so it is already part of `internal`.
    const columns = orderWithinRanks(ids, rank, internal)
    const block = layoutColumns(columns, () => ({ width: CHILD_W, height: CHILD_H }), CHILD_GAP_X, CHILD_GAP_Y)
    groupBlocks.set(groupId, block)
  }

  const sizeOf = (id: string) => {
    const group = groupBlocks.get(id)
    if (group) {
      return { width: group.width + GROUP_PAD * 2, height: group.height + GROUP_PAD + GROUP_HEADER }
    }
    return { width: NODE_W, height: nodeHeight(byId.get(id)!, showConfig) }
  }

  const stageIds = [...graph.stages.map((s) => s.id as number | null)]
  if (topLevel.some((n) => n.stage === null || !stageIds.includes(n.stage))) stageIds.push(null)

  const nodes: Record<string, LaidOutNode> = {}
  const lanes: LaneBand[] = []
  let y = 0
  let order = 0
  let maxWidth = 0

  for (const stage of stageIds) {
    const members = topLevel.filter((n) => (stageIds.includes(n.stage) ? n.stage : null) === stage)
    if (members.length === 0) continue
    const groups = members.filter((n) => groupBlocks.has(n.id)).sort((a, b) => a.id.localeCompare(b.id))
    const plain = members.filter((n) => !groupBlocks.has(n.id))
    const laneTop = y
    let cursorY = y + LANE_PAD_Y
    let laneWidth = 0

    for (const group of groups) {
      const block = groupBlocks.get(group.id)!
      const size = sizeOf(group.id)
      const gx = LANE_LABEL_W
      nodes[group.id] = { id: group.id, kind: 'group', x: gx, y: cursorY, width: size.width, height: size.height, order: order++ }
      const childColumns = Object.entries(block.placed).sort((a, b) => a[1].x - b[1].x || a[1].y - b[1].y)
      for (const [childId, rect] of childColumns) {
        const rx = GROUP_PAD + rect.x
        const ry = GROUP_HEADER + rect.y
        nodes[childId] = {
          id: childId,
          kind: 'child',
          x: gx + rx,
          y: cursorY + ry,
          width: rect.width,
          height: rect.height,
          relative: { x: rx, y: ry },
          order: order++,
        }
      }
      laneWidth = Math.max(laneWidth, size.width)
      cursorY += size.height + ROW_GAP
    }

    if (plain.length > 0) {
      const ids = plain.map((n) => n.id)
      const laneEdges = lifted.filter((e) => ids.includes(e.source) && ids.includes(e.target) && e.kind !== 'trace')
      const rank = rankNodes(ids, laneEdges)
      // A node with no edge inside its lane has no rank to speak of; give each its own
      // column after the ranked ones so they sit side by side instead of piling up.
      const connected = new Set(laneEdges.flatMap((e) => [e.source, e.target]))
      let nextColumn = Math.max(-1, ...ids.filter((id) => connected.has(id)).map((id) => rank[id])) + 1
      for (const id of [...ids].sort()) if (!connected.has(id)) rank[id] = nextColumn++
      const columns = orderWithinRanks(ids, rank, lifted)
      const block = layoutColumns(columns, sizeOf, GAP_X, GAP_Y)
      const sorted = Object.entries(block.placed).sort((a, b) => a[1].x - b[1].x || a[1].y - b[1].y)
      for (const [id, rect] of sorted) {
        nodes[id] = { id, kind: 'module', x: LANE_LABEL_W + rect.x, y: cursorY + rect.y, width: rect.width, height: rect.height, order: order++ }
      }
      laneWidth = Math.max(laneWidth, block.width)
      cursorY += block.height + ROW_GAP
    }

    const laneHeight = cursorY - ROW_GAP + LANE_PAD_Y - laneTop
    const meta = graph.stages.find((s) => s.id === stage)
    lanes.push({ stage, label: meta ? meta.label : 'Not placed yet', x: 0, y: laneTop, width: 0, height: laneHeight })
    maxWidth = Math.max(maxWidth, LANE_LABEL_W + laneWidth)
    y = laneTop + laneHeight + LANE_GAP
  }

  const width = maxWidth + 24
  for (const lane of lanes) lane.width = width
  return { nodes, lanes, width, height: Math.max(0, y - LANE_GAP) }
}

// ---- Edge geometry ---------------------------------------------------------------------

export interface EdgePath {
  d: string
  /** Sampled points along the path, for transform-only packet animation. */
  points: { x: number; y: number }[]
  labelAt: { x: number; y: number }
}

function cubic(p0: number, p1: number, p2: number, p3: number, t: number): number {
  const m = 1 - t
  return m * m * m * p0 + 3 * m * m * t * p1 + 3 * m * t * t * p2 + t * t * t * p3
}

/** A cubic curve between two node rectangles, leaving and entering on the sides that face
 * each other. Same-row edges that point backwards arc over the top so they do not run
 * through the nodes between them. */
export function edgePath(a: Rect, b: Rect, samples = 24): EdgePath {
  const ac = { x: a.x + a.width / 2, y: a.y + a.height / 2 }
  const bc = { x: b.x + b.width / 2, y: b.y + b.height / 2 }
  const overlapsVertically = a.y < b.y + b.height && b.y < a.y + a.height
  let p0: { x: number; y: number }
  let p3: { x: number; y: number }
  let c1: { x: number; y: number }
  let c2: { x: number; y: number }

  if (overlapsVertically && b.x >= a.x + a.width) {
    p0 = { x: a.x + a.width, y: ac.y }
    p3 = { x: b.x, y: bc.y }
    const bend = Math.max(24, (p3.x - p0.x) / 2)
    c1 = { x: p0.x + bend, y: p0.y }
    c2 = { x: p3.x - bend, y: p3.y }
  } else if (overlapsVertically) {
    // Backwards on the same row: arc above.
    p0 = { x: ac.x, y: a.y }
    p3 = { x: bc.x, y: b.y }
    const lift = Math.min(90, 28 + Math.abs(p0.x - p3.x) * 0.18)
    c1 = { x: p0.x, y: p0.y - lift }
    c2 = { x: p3.x, y: p3.y - lift }
  } else if (b.y >= a.y + a.height) {
    p0 = { x: ac.x, y: a.y + a.height }
    p3 = { x: bc.x, y: b.y }
    const bend = Math.max(24, (p3.y - p0.y) / 2)
    c1 = { x: p0.x, y: p0.y + bend }
    c2 = { x: p3.x, y: p3.y - bend }
  } else {
    p0 = { x: ac.x, y: a.y }
    p3 = { x: bc.x, y: b.y + b.height }
    const bend = Math.max(24, (p0.y - p3.y) / 2)
    c1 = { x: p0.x, y: p0.y - bend }
    c2 = { x: p3.x, y: p3.y + bend }
  }

  const points = Array.from({ length: samples + 1 }, (_, i) => {
    const t = i / samples
    return { x: cubic(p0.x, c1.x, c2.x, p3.x, t), y: cubic(p0.y, c1.y, c2.y, p3.y, t) }
  })
  return {
    d: `M ${p0.x} ${p0.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${p3.x} ${p3.y}`,
    points,
    labelAt: points[Math.floor(samples / 2)],
  }
}

/** Every node that can reach `id` or be reached from it, including `id` itself. */
export function connectedPath(id: string, edges: ArchitectureEdge[], nodes: ArchitectureNode[]): Set<string> {
  const parentOf = new Map(nodes.map((n) => [n.id, n.parent]))
  const childrenOf = new Map<string, string[]>()
  for (const n of nodes) if (n.parent) childrenOf.set(n.parent, [...(childrenOf.get(n.parent) ?? []), n.id])
  const walk = (start: string, direction: 'down' | 'up') => {
    const seen = new Set<string>([start])
    const queue = [start]
    while (queue.length > 0) {
      const current = queue.shift()!
      for (const e of edges) {
        const from = direction === 'down' ? e.source : e.target
        const to = direction === 'down' ? e.target : e.source
        if (from !== current || seen.has(to)) continue
        seen.add(to)
        queue.push(to)
      }
    }
    return seen
  }
  const result = new Set([...walk(id, 'down'), ...walk(id, 'up')])
  // A group and its members light up together.
  for (const member of [...result]) {
    const parent = parentOf.get(member)
    if (parent) result.add(parent)
  }
  for (const child of childrenOf.get(id) ?? []) result.add(child)
  return result
}
