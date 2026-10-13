/** Turning real trace events into what the diagram shows. Everything here is a pure function
 * of the events received; nothing invents an event or advances on a timer. */
import type { ArchitectureGraph, TraceEvent } from '@/lib/api/types'

export type NodeActivity = 'idle' | 'active' | 'done' | 'error' | 'blocked'

/** Latest status per node, across the sessions being watched. */
export function nodeActivity(events: TraceEvent[], stageToNode: Record<string, string>): Record<string, NodeActivity> {
  const result: Record<string, NodeActivity> = {}
  const ordered = [...events].sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at) || a.seq - b.seq)
  for (const event of ordered) {
    const node = stageToNode[event.stage]
    if (!node) continue
    result[node] =
      event.status === 'running' || event.status === 'retrying' || event.status === 'queued'
        ? 'active'
        : event.status === 'error'
          ? 'error'
          : event.status === 'blocked'
            ? 'blocked'
            : 'done'
  }
  return result
}

/** Shortest chain of edges from one node to another, at most `maxHops` long. */
export function findRoute(
  from: string,
  to: string,
  edges: ArchitectureGraph['edges'],
  maxHops = 3,
): string[] | null {
  if (from === to) return []
  const queue: { node: string; path: string[] }[] = [{ node: from, path: [] }]
  const seen = new Set([from])
  while (queue.length > 0) {
    const { node, path } = queue.shift()!
    if (path.length >= maxHops) continue
    for (const edge of edges) {
      if (edge.source !== node || seen.has(edge.target)) continue
      const next = [...path, edge.id]
      if (edge.target === to) return next
      seen.add(edge.target)
      queue.push({ node: edge.target, path: next })
    }
  }
  return null
}

export interface Hop {
  key: string
  edgeIds: string[]
  /** Measured latency of the stage that produced this hop, in ms. Null when not yet known. */
  measuredMs: number | null
  sessionId: string
}

/**
 * The hop a newly arrived event represents, if any.
 *
 * - A stage starting (`running`) means the previous stage in that session handed off to it:
 *   the packet runs from the previous stage's node to this one, at a speed set by how long
 *   the previous stage actually took.
 * - The first stage of a session is reached from the node named by `from_stage` (the browser,
 *   for a chat turn or an upload).
 * - A stage finishing with a `to_stage` that has no trace stage of its own (the browser) is
 *   the answer leaving.
 */
export function hopFor(event: TraceEvent, earlier: TraceEvent[], graph: ArchitectureGraph): Hop | null {
  const target = graph.stage_to_node[event.stage]
  if (!target) return null

  if (event.status === 'running') {
    const finished = [...earlier]
      .filter((e) => e.session_id === event.session_id && e.seq < event.seq && e.status !== 'running' && e.stage !== event.stage)
      .sort((a, b) => b.seq - a.seq)
    const justFinished = finished[0]
    // Usually the stage that just finished hands off directly. When it does not connect to
    // this one (enrichment stages fan out from earlier results), walk back to the nearest
    // earlier stage that does; failing that, use where the event says it came from.
    const candidates = [...finished.map((e) => e.stage), ...(event.from_stage ? [event.from_stage] : [])]
    for (const stage of candidates) {
      const source = graph.stage_to_node[stage]
      if (!source || source === target) continue
      const route = findRoute(source, target, graph.edges)
      if (route && route.length > 0) {
        return { key: `${event.session_id}:${event.seq}`, edgeIds: route, measuredMs: justFinished?.duration_ms ?? null, sessionId: event.session_id }
      }
    }
    return null
  }

  if (event.status === 'done' && event.to_stage === 'client') {
    const destination = graph.stage_to_node.client
    if (!destination) return null
    const route = findRoute(target, destination, graph.edges)
    if (!route || route.length === 0) return null
    return { key: `${event.session_id}:${event.seq}:out`, edgeIds: route, measuredMs: event.duration_ms, sessionId: event.session_id }
  }
  return null
}

export const PACKET_MIN_MS = 320
export const PACKET_MAX_MS = 4000

/** How long a packet takes to cross its route. Proportional to the measured latency of the
 * stage it stands for, so a slow stage visibly crawls; clamped so a 2ms stage is still
 * visible and a 90s one does not hold the screen. */
export function packetDurationMs(measuredMs: number | null): number {
  if (measuredMs === null || Number.isNaN(measuredMs)) return PACKET_MIN_MS
  return Math.round(Math.max(PACKET_MIN_MS, Math.min(PACKET_MAX_MS, PACKET_MIN_MS + measuredMs * 0.08)))
}

/** History replayed on (re)connect arrives all at once; only events that are actually
 * happening now are animated. */
export function isLive(event: TraceEvent, now = Date.now(), toleranceMs = 15_000): boolean {
  const started = Date.parse(event.started_at.endsWith('Z') || /[+-]\d\d:\d\d$/.test(event.started_at) ? event.started_at : `${event.started_at}Z`)
  const ended = started + (event.duration_ms ?? 0)
  return now - ended < toleranceMs
}
