/// <reference types="node" />
// src/** compiles under tsconfig.app.json (types: ["vite/client"] only, no Node globals) —
// this is the one file under src/ that reads process.env (a vitest/Node runtime, not a
// browser one), so it needs @types/node locally rather than widening the whole app project.
import { describe, expect, it } from 'vitest'
import { NODE_LAYOUT, EDGE_LAYOUT } from './architectureLayout'
import { ARCH_ICON_BY_NODE } from './ArchIcons'

/** AR-5's contract test: the hand-authored frontend layout/icon set can never silently drift
 * from the real backend topology (GET /api/v1/architecture/topology). Requires a running
 * backend — same assumption the Playwright E2E suite already makes (see tests/e2e/README.md)
 * — rather than comparing against a hand-maintained mirror that could itself drift unnoticed.
 * Override with VITEST_BACKEND_PORT if the backend isn't on the default port. */
const backendPort = process.env.VITEST_BACKEND_PORT ?? '8000'
const backendUrl = `http://localhost:${backendPort}/api/v1/architecture/topology`

interface BackendNode {
  id: string
  module_path: string
  group: string | null
  stage: number | null
  planned: boolean
}
interface BackendEdge {
  source: string
  target: string
}
interface Topology {
  nodes: BackendNode[]
  edges: BackendEdge[]
}

async function fetchTopology(): Promise<Topology> {
  let resp: Response
  try {
    resp = await fetch(backendUrl)
  } catch (err) {
    throw new Error(
      `Could not reach the backend at ${backendUrl} to run the architecture contract test. ` +
        `Start it first (e.g. "make backend-dev") — this test intentionally fails rather than ` +
        `skipping, so a drifted layout is never silently unverified. Original error: ${err}`,
    )
  }
  if (!resp.ok) {
    throw new Error(`GET ${backendUrl} returned ${resp.status}`)
  }
  return resp.json() as Promise<Topology>
}

describe('architecture layout vs real backend topology', () => {
  it('every non-planned backend node has a frontend layout entry and an icon', async () => {
    const topology = await fetchTopology()
    const missingLayout: string[] = []
    const missingIcon: string[] = []
    for (const node of topology.nodes) {
      if (node.planned) continue
      if (!(node.id in NODE_LAYOUT)) missingLayout.push(node.id)
      if (!(node.id in ARCH_ICON_BY_NODE)) missingIcon.push(node.id)
    }
    expect(missingLayout, `backend nodes with no NODE_LAYOUT entry: ${missingLayout.join(', ')}`).toEqual([])
    expect(missingIcon, `backend nodes with no ArchIcons entry: ${missingIcon.join(', ')}`).toEqual([])
  })

  it('every frontend layout node corresponds to a real (or explicitly planned) backend node', async () => {
    const topology = await fetchTopology()
    const backendIds = new Set(topology.nodes.map((n) => n.id))
    const orphaned = Object.keys(NODE_LAYOUT).filter((id) => !backendIds.has(id))
    expect(orphaned, `layout nodes with no matching backend node: ${orphaned.join(', ')}`).toEqual([])
  })

  it('every edge endpoint exists as a node in both the frontend layout and the backend topology', async () => {
    const topology = await fetchTopology()
    const backendIds = new Set(topology.nodes.map((n) => n.id))
    for (const edge of EDGE_LAYOUT) {
      expect(edge.source in NODE_LAYOUT, `edge ${edge.id}: unknown source "${edge.source}"`).toBe(true)
      expect(edge.target in NODE_LAYOUT, `edge ${edge.id}: unknown target "${edge.target}"`).toBe(true)
      expect(backendIds.has(edge.source), `edge ${edge.id}: source "${edge.source}" not in backend topology`).toBe(
        true,
      )
      expect(backendIds.has(edge.target), `edge ${edge.id}: target "${edge.target}" not in backend topology`).toBe(
        true,
      )
    }
  })

  it('planned nodes (dashed outline, never receive light) are never a light-flow edge endpoint', async () => {
    const topology = await fetchTopology()
    const plannedIds = new Set(topology.nodes.filter((n) => n.planned).map((n) => n.id))
    if (plannedIds.size === 0) return
    for (const edge of EDGE_LAYOUT) {
      expect(plannedIds.has(edge.source), `edge ${edge.id} starts at a planned node`).toBe(false)
      expect(plannedIds.has(edge.target), `edge ${edge.id} ends at a planned node`).toBe(false)
    }
  })
})
