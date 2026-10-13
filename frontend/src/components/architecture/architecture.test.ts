import { describe, expect, it } from 'vitest'
import type { ArchitectureEdge, ArchitectureGraph, ArchitectureNode, TraceEvent } from '@/lib/api/types'
import { connectedPath, edgePath, layoutGraph, rankNodes } from './layout'
import { buildScene } from './scene'
import { findRoute, hopFor, isLive, nodeActivity, packetDurationMs, PACKET_MAX_MS, PACKET_MIN_MS } from './trace'

/** A made-up topology on purpose: none of these ids exist in the real backend, which is the
 * point — the frontend has no node list of its own and must draw whatever it is given. */
function node(id: string, stage: number | null, extra: Partial<ArchitectureNode> = {}): ArchitectureNode {
  return {
    id,
    label: id,
    module_path: `app.${id}`,
    one_line_purpose: `${id} does something`,
    stage,
    parent: null,
    documented: true,
    status: 'healthy',
    status_detail: 'ok',
    probe_kind: 'import',
    probe_id: null,
    trace_stages: [id],
    invocation_count: 0,
    error_count: 0,
    last_latency_ms: null,
    last_at: null,
    p50_latency_ms: null,
    p95_latency_ms: null,
    latency_sample_size: 0,
    config: {},
    source_path: `backend/app/${id}`,
    source_abs_path: `/repo/backend/app/${id}`,
    ...extra,
  }
}

function edge(source: string, target: string, kind: ArchitectureEdge['kind'] = 'data'): ArchitectureEdge {
  return { id: `${source}->${target}`, source, target, kind, label: '', derived: 'declared' }
}

function fixture(): ArchitectureGraph {
  const nodes = [
    node('browser', 3),
    node('gate', 3),
    node('reader', 1),
    node('masker', 1),
    node('slicer', 2, { config: { size: 512, overlap: 64, mode: 'x', extra: 'y' } }),
    node('vectors', 2),
    node('brain', 2),
    node('brain.plan', 2, { parent: 'brain', trace_stages: ['plan'] }),
    node('brain.fetch', 2, { parent: 'brain', trace_stages: ['fetch'] }),
    node('brain.judge', 2, { parent: 'brain', trace_stages: ['judge'] }),
    node('orphan', null, { documented: false }),
  ]
  const edges = [
    edge('browser', 'gate', 'request'),
    edge('gate', 'reader', 'request'),
    edge('reader', 'masker'),
    edge('masker', 'slicer'),
    edge('slicer', 'vectors'),
    edge('gate', 'brain.plan', 'request'),
    edge('brain.plan', 'brain.fetch'),
    edge('brain.fetch', 'brain.judge'),
    edge('brain.judge', 'brain.fetch', 'optional'),
    edge('brain.judge', 'gate'),
    edge('gate', 'browser', 'trace'),
  ]
  const stage_to_node: Record<string, string> = { client: 'browser' }
  for (const n of nodes) for (const s of n.trace_stages) stage_to_node[s] ??= n.id
  return {
    generated_at: '2026-01-01T00:00:00Z',
    stats_since: '2026-01-01T00:00:00Z',
    stages: [
      { id: 1, label: 'One', description: 'first' },
      { id: 2, label: 'Two', description: 'second' },
      { id: 3, label: 'Three', description: 'third' },
    ],
    nodes,
    edges,
    stage_to_node,
  }
}

function overlaps(a: { x: number; y: number; width: number; height: number }, b: typeof a): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
}

describe('layoutGraph', () => {
  it('is deterministic: the same payload always produces the same picture', () => {
    const a = layoutGraph(fixture(), { showConfig: true })
    const b = layoutGraph(fixture(), { showConfig: true })
    expect(a).toEqual(b)
  })

  it('places every node it is given, including ones the frontend has never heard of', () => {
    const graph = fixture()
    const layout = layoutGraph(graph, { showConfig: false })
    expect(Object.keys(layout.nodes).sort()).toEqual(graph.nodes.map((n) => n.id).sort())
  })

  it('never overlaps two top-level nodes, and keeps group members inside their group', () => {
    const graph = fixture()
    const layout = layoutGraph(graph, { showConfig: true })
    const top = Object.values(layout.nodes).filter((n) => n.kind !== 'child')
    for (let i = 0; i < top.length; i += 1) {
      for (let j = i + 1; j < top.length; j += 1) {
        expect(overlaps(top[i], top[j]), `${top[i].id} overlaps ${top[j].id}`).toBe(false)
      }
    }
    const group = layout.nodes.brain
    for (const child of Object.values(layout.nodes).filter((n) => n.kind === 'child')) {
      expect(child.x).toBeGreaterThanOrEqual(group.x)
      expect(child.y).toBeGreaterThanOrEqual(group.y)
      expect(child.x + child.width).toBeLessThanOrEqual(group.x + group.width)
      expect(child.y + child.height).toBeLessThanOrEqual(group.y + group.height)
    }
  })

  it('follows the flow: a node sits to the right of what feeds it within a lane', () => {
    const layout = layoutGraph(fixture(), { showConfig: false })
    expect(layout.nodes.masker.x).toBeGreaterThan(layout.nodes.reader.x)
    expect(layout.nodes.vectors.x).toBeGreaterThan(layout.nodes.slicer.x)
    expect(layout.nodes['brain.fetch'].x).toBeGreaterThan(layout.nodes['brain.plan'].x)
    // Stages stack in story order.
    expect(layout.nodes.slicer.y).toBeGreaterThan(layout.nodes.reader.y)
    expect(layout.nodes.gate.y).toBeGreaterThan(layout.nodes.slicer.y)
  })

  it('changes when the topology changes, with no other input', () => {
    const before = layoutGraph(fixture(), { showConfig: false })
    const smaller = fixture()
    smaller.nodes = smaller.nodes.filter((n) => n.id !== 'vectors')
    smaller.edges = smaller.edges.filter((e) => e.source !== 'vectors' && e.target !== 'vectors')
    const after = layoutGraph(smaller, { showConfig: false })
    expect(after.nodes.vectors).toBeUndefined()
    expect(Object.keys(after.nodes)).toHaveLength(Object.keys(before.nodes).length - 1)
  })

  it('gives a module with visible config more room in Detailed than in Live Trace', () => {
    const detailed = layoutGraph(fixture(), { showConfig: true })
    const compact = layoutGraph(fixture(), { showConfig: false })
    expect(detailed.nodes.slicer.height).toBeGreaterThan(compact.nodes.slicer.height)
  })

  it('puts a package with no stage in its own lane instead of dropping it', () => {
    const layout = layoutGraph(fixture(), { showConfig: false })
    expect(layout.nodes.orphan).toBeDefined()
    expect(layout.lanes.at(-1)?.stage).toBeNull()
  })
})

describe('rankNodes', () => {
  it('survives cycles by ignoring back edges', () => {
    const rank = rankNodes(['a', 'b', 'c'], [
      { source: 'a', target: 'b' },
      { source: 'b', target: 'c' },
      { source: 'c', target: 'a' },
    ])
    expect(rank).toEqual({ a: 0, b: 1, c: 2 })
  })
})

describe('edgePath', () => {
  it('starts and ends on the facing sides of the two nodes', () => {
    const a = { x: 0, y: 0, width: 100, height: 40 }
    const b = { x: 300, y: 0, width: 100, height: 40 }
    const path = edgePath(a, b)
    expect(path.points[0]).toEqual({ x: 100, y: 20 })
    expect(path.points.at(-1)).toEqual({ x: 300, y: 20 })
  })
})

describe('connectedPath', () => {
  it('returns everything upstream and downstream of a node', () => {
    const graph = fixture()
    const path = connectedPath('masker', graph.edges, graph.nodes)
    expect(path.has('reader')).toBe(true)
    expect(path.has('slicer')).toBe(true)
    expect(path.has('vectors')).toBe(true)
    expect(path.has('orphan')).toBe(false)
  })
})

describe('buildScene', () => {
  it('collapses to one node per stage in Overview and merges the edges between stages', () => {
    const scene = buildScene(fixture(), 'overview')
    expect(scene.nodes.map((n) => n.id)).toEqual(['stage:1', 'stage:2', 'stage:3', 'stage:none'])
    const ids = scene.edges.map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(scene.edgeFor['reader->masker']).toBeUndefined() // same stage: nothing to draw
    expect(scene.edgeFor['masker->slicer']).toBe('stage:1->stage:2')
    expect(scene.nodeFor['brain.plan']).toBe('stage:2')
  })

  it('draws every edge between placed nodes in Detailed', () => {
    const graph = fixture()
    const scene = buildScene(graph, 'detailed')
    expect(scene.edges).toHaveLength(graph.edges.length)
    expect(scene.edgeFor['gate->brain.plan']).toBe('gate->brain.plan')
  })
})

function ev(partial: Partial<TraceEvent> & Pick<TraceEvent, 'seq' | 'stage' | 'status'>): TraceEvent {
  return {
    trace_id: `t${partial.seq}`,
    session_id: 's1',
    started_at: '2026-01-01T00:00:00Z',
    duration_ms: null,
    from_stage: null,
    to_stage: null,
    input_preview: null,
    output_preview: null,
    metrics: {},
    ...partial,
  }
}

describe('trace → diagram', () => {
  it('finds a multi-hop route and refuses one that is too long', () => {
    const graph = fixture()
    expect(findRoute('browser', 'brain.plan', graph.edges)).toEqual(['browser->gate', 'gate->brain.plan'])
    expect(findRoute('reader', 'vectors', graph.edges, 2)).toBeNull()
    expect(findRoute('vectors', 'reader', graph.edges)).toBeNull()
  })

  it('reaches the first stage of a session from where the event says it came from', () => {
    const graph = fixture()
    const first = ev({ seq: 0, stage: 'plan', status: 'running', from_stage: 'client' })
    expect(hopFor(first, [], graph)?.edgeIds).toEqual(['browser->gate', 'gate->brain.plan'])
  })

  it('runs a hop from the stage that just finished, carrying that stage’s measured latency', () => {
    const graph = fixture()
    const done = ev({ seq: 1, stage: 'plan', status: 'done', duration_ms: 4200 })
    const next = ev({ seq: 2, stage: 'fetch', status: 'running' })
    const hop = hopFor(next, [done], graph)
    expect(hop?.edgeIds).toEqual(['brain.plan->brain.fetch'])
    expect(hop?.measuredMs).toBe(4200)
  })

  it('walks back to the nearest earlier stage that connects when the last one does not', () => {
    const graph = fixture()
    // vectors has no outgoing edge, so a stage after it is reached from further back.
    const earlier = [
      ev({ seq: 0, stage: 'masker', status: 'done', duration_ms: 10 }),
      ev({ seq: 1, stage: 'vectors', status: 'done', duration_ms: 700 }),
    ]
    const hop = hopFor(ev({ seq: 2, stage: 'slicer', status: 'running' }), earlier, graph)
    expect(hop?.edgeIds).toEqual(['masker->slicer'])
    expect(hop?.measuredMs).toBe(700) // still timed by the stage that just finished
  })

  it('sends the answer back to the browser when the last stage finishes', () => {
    const graph = fixture()
    const last = ev({ seq: 9, stage: 'judge', status: 'done', duration_ms: 30, to_stage: 'client' })
    expect(hopFor(last, [], graph)?.edgeIds).toEqual(['brain.judge->gate', 'gate->browser'])
  })

  it('produces nothing for a stage that is not on the diagram', () => {
    expect(hopFor(ev({ seq: 3, stage: 'unknown_stage', status: 'running' }), [], fixture())).toBeNull()
  })

  it('makes a slow stage crawl and a fast one quick, within bounds', () => {
    expect(packetDurationMs(null)).toBe(PACKET_MIN_MS)
    expect(packetDurationMs(1)).toBeLessThan(packetDurationMs(5_000))
    expect(packetDurationMs(5_000)).toBeLessThan(packetDurationMs(30_000))
    expect(packetDurationMs(10_000_000)).toBe(PACKET_MAX_MS)
  })

  it('treats replayed history as history, not as something happening now', () => {
    const now = Date.parse('2026-01-01T00:10:00Z')
    expect(isLive(ev({ seq: 0, stage: 'plan', status: 'done', started_at: '2026-01-01T00:00:00Z', duration_ms: 500 }), now)).toBe(false)
    expect(isLive(ev({ seq: 1, stage: 'plan', status: 'running', started_at: '2026-01-01T00:09:58Z' }), now)).toBe(true)
    // The backend sends naive UTC timestamps.
    expect(isLive(ev({ seq: 2, stage: 'plan', status: 'running', started_at: '2026-01-01T00:09:58' }), now)).toBe(true)
  })

  it('derives each node’s state purely from the events', () => {
    const graph = fixture()
    const events = [
      ev({ seq: 0, stage: 'plan', status: 'running' }),
      ev({ seq: 1, stage: 'plan', status: 'done', duration_ms: 5 }),
      ev({ seq: 2, stage: 'fetch', status: 'running' }),
      ev({ seq: 3, stage: 'judge', status: 'error', duration_ms: 9 }),
    ]
    expect(nodeActivity(events, graph.stage_to_node)).toEqual({
      'brain.plan': 'done',
      'brain.fetch': 'active',
      'brain.judge': 'error',
    })
    expect(nodeActivity([], graph.stage_to_node)).toEqual({})
  })
})
