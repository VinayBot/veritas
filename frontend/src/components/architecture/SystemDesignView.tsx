import { useEffect, useMemo, useRef, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { Bot, Download, Image as ImageIcon, Info, Maximize2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TraceEvent } from '@/lib/api/types'
import { RobotCharacter } from '@/components/robot/robot-character'
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  EDGE_LAYOUT,
  EDGE_LAYOUT_BY_ID,
  GROUP_BOXES,
  NODE_LAYOUT,
  type EdgeLayout,
} from './architectureLayout'
import { ARCH_ICON_BY_NODE } from './ArchIcons'
import { LightFlowDock, type LightFlowSpeed } from './LightFlowDock'
import { NodeInfoCard, type NodeInfoCardData } from './NodeInfoCard'
import { LIGHT_FLOW_STAGES } from './lightFlowStages'
import { PIPELINE_STAGE_TO_EDGE } from './traceStageMapping'
import { exportArchitecturePng, exportArchitectureSvg } from './architectureExport'
import type { ArchitectureTopologyResponse } from '@/lib/api/types'

const COMET_SPEED_PX_PER_S = 280
const MAX_CONCURRENT_COMETS = 6

interface MergedNode {
  id: string
  label: string
  modulePath: string
  purpose: string
  group: string | null
  planned: boolean
}

const PURPOSE_BY_NODE: Record<string, string> = {
  user: 'The React UI running in the browser.',
  gateway: 'FastAPI app entrypoint — CORS, request ids, size limits.',
  guardrails_in: 'Input guardrails: regex heuristics, prompt-injection classifier, Llama Guard.',
  router: 'Validates and routes the chosen chat mode (adaptive/agentic/hybrid/graph/council).',
  orchestrator: 'LangGraph pipeline: planner, rewriter, retriever, critic, synthesizer, verifier, guardian.',
  event_bus: 'In-process trace event stream, replayed and streamed live over /ws/trace/{session_id}.',
  llm_providers: 'LiteLLM routing to Ollama / Claude / Groq / Gemini.',
  index_manager: 'Hybrid retrieval: RRF fusion, HyDE, reranking, dedup.',
  index_dense: 'Dense vector index (ChromaDB).',
  index_sparse: 'Sparse lexical index (BM25).',
  index_graph: 'Entity/relation graph index (NetworkX).',
  metadb: 'SQLite + SQLAlchemy: documents, conversations, runs, audit log.',
  cache: 'Embedding/answer cache keyed on query + corpus version.',
  pii_vault: 'Presidio detection + HMAC tokenization + Fernet-encrypted vault.',
  trace_ids: 'Issues request/trace/document ids.',
  ingest_scheduler: 'Runs ingestion as a detached background job per document.',
  evaluator: 'Synthetic eval sets, metrics, LLM judge, Advisor, benchmark, red-team.',
  council_member_1: 'One of three independent LLM Council answers.',
  council_member_2: 'One of three independent LLM Council answers.',
  council_chairman: "Peer-reviews the council's answers and picks the final one.",
  worker_docling: 'Layout-aware document parsing (Docling).',
  worker_scraper: 'URL scraping with an SSRF guard.',
  worker_refiner: 'Chunking + embedding + GraphRAG extraction.',
}

function buildMergedNodes(topology: ArchitectureTopologyResponse | null): Record<string, MergedNode> {
  const result: Record<string, MergedNode> = {}
  const backendById = new Map(topology?.nodes.map((n) => [n.id, n]) ?? [])
  for (const id of Object.keys(NODE_LAYOUT)) {
    const backend = backendById.get(id)
    result[id] = {
      id,
      label: backend?.label ?? id,
      modulePath: backend?.module_path ?? 'unknown',
      purpose: PURPOSE_BY_NODE[id] ?? '',
      group: backend?.group ?? null,
      planned: backend?.planned ?? false,
    }
  }
  return result
}

function edgePathD(edge: EdgeLayout): string {
  return edge.points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
}

/** Edges are orthogonal (axis-aligned segments only), so Manhattan length is exact. */
function edgeLength(edge: EdgeLayout): number {
  let total = 0
  for (let i = 1; i < edge.points.length; i++) {
    const a = edge.points[i - 1]
    const b = edge.points[i]
    total += Math.abs(b.x - a.x) + Math.abs(b.y - a.y)
  }
  return total
}

interface NodeStats {
  status: string
  durationsMs: number[]
  lastEventAt: string | null
}

function computeNodeStats(events: TraceEvent[]): Record<string, NodeStats> {
  const stats: Record<string, NodeStats> = {}
  for (const event of events) {
    const edgeId = PIPELINE_STAGE_TO_EDGE[event.stage]
    if (!edgeId) continue
    const edge = EDGE_LAYOUT_BY_ID[edgeId]
    if (!edge) continue
    const nodeId = edge.target
    const existing = stats[nodeId] ?? { status: 'idle', durationsMs: [], lastEventAt: null }
    existing.status = event.status
    existing.lastEventAt = event.started_at
    if (event.duration_ms !== null) existing.durationsMs.push(event.duration_ms)
    stats[nodeId] = existing
  }
  return stats
}

interface ActiveComet {
  key: number
  edgeId: string
  color: string
  reply: boolean
}

export interface SystemDesignViewProps {
  topology: ArchitectureTopologyResponse | null
  events: TraceEvent[]
  connected: boolean
}

export function SystemDesignView({ topology, events, connected }: SystemDesignViewProps) {
  const reduced = useReducedMotion()
  const svgRef = useRef<SVGSVGElement>(null)
  const cometLayerRef = useRef<SVGGElement>(null)
  const robotRef = useRef<SVGGElement>(null)
  const nodeRefs = useRef<Map<string, SVGGElement>>(new Map())
  const [comets, setComets] = useState<ActiveComet[]>([])
  const cometCounter = useRef(0)
  // Bumped on every explicit Tour jump (prev/next/select-stage) so an in-flight comet's
  // completion callback — captured from before the jump — can tell it's stale and skip
  // advancing tourEdgeIndex a second time. Without this, jumping stages while a comet was
  // still animating double-advanced the index once the old comet's `.then()` finally fired
  // (confirmed live: observed edge sequence skipped/duplicated entries after a stage jump).
  const tourEpoch = useRef(0)
  const [currentEdgeId, setCurrentEdgeId] = useState<string | null>(null)
  // Append-only log of every edge a comet started on (newest last, capped), exposed via
  // data-edge-history. A test (or a developer) polling the single `data-current-edge`
  // snapshot can land between two polls and miss a short edge entirely; this cumulative log
  // can't be missed the same way, since it only grows. Manual jumps clear `currentEdgeId`
  // but never this — it's a pure history, not a "what's showing right now" value.
  const [edgeHistory, setEdgeHistory] = useState<string[]>([])
  function markEdgeActive(edgeId: string) {
    setCurrentEdgeId(edgeId)
    setEdgeHistory((prev) => [...prev, edgeId].slice(-40))
  }

  const [tourStageIndex, setTourStageIndex] = useState(0)
  const [tourEdgeIndex, setTourEdgeIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState<LightFlowSpeed>(1)
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)
  const [pinnedNode, setPinnedNode] = useState<string | null>(null)
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 })
  const [legendOpen, setLegendOpen] = useState(false)
  const [showInfoPopover, setShowInfoPopover] = useState(false)
  const [visible, setVisible] = useState(true)
  const [mode, setMode] = useState<'tour' | 'live'>('tour')
  const [showRobot, setShowRobot] = useState(true)
  const dragState = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null)

  const mergedNodes = useMemo(() => buildMergedNodes(topology), [topology])
  const nodeStats = useMemo(() => computeNodeStats(events), [events])
  const activeStage = LIGHT_FLOW_STAGES[tourStageIndex]
  const hasInFlightEvent = events.some((e) => e.status === 'running' || e.status === 'retrying')

  // LF-3: Live is the default whenever a request is in flight. A manual pick of either mode
  // sticks until the NEXT in-flight request starts — at that point Live takes over again, so
  // the canvas never looks idle while something real is actually happening.
  useEffect(() => {
    if (hasInFlightEvent) {
      tourEpoch.current++
      setMode('live')
    }
  }, [hasInFlightEvent])

  function onModeChange(next: 'tour' | 'live') {
    tourEpoch.current++
    // Otherwise a mode switch shows a stale "current edge" left over from whatever was
    // mid-flight in the OLD mode — confirmed live: switching to Live right after Tour mode
    // still showed Tour's last edge as "current" even with nothing real in flight.
    setCurrentEdgeId(null)
    setMode(next)
  }

  // G9: pause all animation off-screen or when the tab is hidden.
  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', onVisibility)
    const el = svgRef.current
    let observer: IntersectionObserver | null = null
    if (el && 'IntersectionObserver' in window) {
      observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting && !document.hidden))
      observer.observe(el)
    }
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      observer?.disconnect()
    }
  }, [])

  function pulseNode(nodeId: string) {
    const el = nodeRefs.current.get(nodeId)
    if (!el || reduced) return
    el.animate(
      [
        { filter: 'drop-shadow(0 0 0px currentColor)', offset: 0 },
        { filter: 'drop-shadow(0 0 14px currentColor)', offset: 0.5 },
        { filter: 'drop-shadow(0 0 0px currentColor)', offset: 1 },
      ],
      { duration: 400, easing: 'ease-out' },
    )
  }

  function fireComet(edgeId: string, color: string, opts: { reply?: boolean; onDone?: () => void } = {}) {
    const edge = EDGE_LAYOUT_BY_ID[edgeId]
    if (!edge || !visible) {
      opts.onDone?.()
      return
    }
    const startEpoch = tourEpoch.current
    const stale = () => tourEpoch.current !== startEpoch
    if (reduced) {
      // LF-6: static step-through highlighting instead of travelling light.
      markEdgeActive(edgeId)
      pulseNode(opts.reply ? edge.source : edge.target)
      const t = window.setTimeout(() => {
        if (!stale()) opts.onDone?.()
      }, 500 / speed)
      return () => window.clearTimeout(t)
    }

    // Increment exactly once, outside the state updater — React 19 StrictMode double-invokes
    // a functional setState updater to catch impurity (see chat.spec.ts's "Bug A" comment for
    // the real incident this codebase already hit from the same class of mistake), so a
    // `cometCounter.current++` read-and-write *inside* the updater below would double-fire.
    const key = cometCounter.current++
    setComets((prev) => [...prev, { key, edgeId, color, reply: !!opts.reply }].slice(-MAX_CONCURRENT_COMETS))
    markEdgeActive(edgeId)

    const length = edgeLength(opts.reply ? { ...edge, points: [...edge.points].reverse() } : edge)
    const durationMs = Math.max(300, (length / COMET_SPEED_PX_PER_S / speed) * 1000)

    const raf = requestAnimationFrame(() => {
      const g = cometLayerRef.current?.querySelector<SVGGElement>(`[data-comet-key="${key}"]`)
      if (!g) {
        opts.onDone?.()
        return
      }
      const d = opts.reply ? edgePathD({ ...edge, points: [...edge.points].reverse() }) : edgePathD(edge)
      g.style.offsetPath = `path("${d}")`
      g.style.offsetRotate = '0deg'
      const anim = g.animate([{ offsetDistance: '0%' }, { offsetDistance: '100%' }], {
        duration: durationMs,
        easing: 'linear',
        fill: 'forwards',
      })
      if (showRobot && robotRef.current && !opts.reply) {
        robotRef.current.style.offsetPath = `path("${d}")`
        robotRef.current.animate([{ offsetDistance: '0%' }, { offsetDistance: '100%' }], {
          duration: durationMs,
          easing: 'linear',
          fill: 'forwards',
        })
      }
      anim.finished
        .then(() => {
          pulseNode(opts.reply ? edge.source : edge.target)
          setComets((prev) => prev.filter((c) => c.key !== key))
          if (!stale()) opts.onDone?.()
        })
        .catch(() => {
          if (!stale()) opts.onDone?.()
        })
    })
    return () => cancelAnimationFrame(raf)
  }

  // Tour mode playback: walk the active stage's edges in order, then advance to the next stage.
  useEffect(() => {
    if (mode !== 'tour' || !playing || !visible) return
    const stage = LIGHT_FLOW_STAGES[tourStageIndex]
    const edgeId = stage.edgeIds[tourEdgeIndex]
    if (!edgeId) {
      const t = window.setTimeout(() => {
        setTourStageIndex((i) => (i + 1) % LIGHT_FLOW_STAGES.length)
        setTourEdgeIndex(0)
      }, 400 / speed)
      return () => window.clearTimeout(t)
    }
    const cleanup = fireComet(edgeId, stage.color, {
      onDone: () => setTourEdgeIndex((i) => i + 1),
    })
    return cleanup
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, playing, visible, tourStageIndex, tourEdgeIndex, speed])

  // Live mode: a comet per real trace event, never a fake/idle one.
  const seenEventKeys = useRef(new Set<string>())
  useEffect(() => {
    if (mode !== 'live') return
    for (const event of events) {
      const key = `${event.trace_id}:${event.seq}`
      if (seenEventKeys.current.has(key)) continue
      seenEventKeys.current.add(key)
      const edgeId = PIPELINE_STAGE_TO_EDGE[event.stage]
      if (edgeId && (event.status === 'running' || event.status === 'done')) {
        const stage = LIGHT_FLOW_STAGES.find((s) => s.edgeIds.includes(edgeId))
        fireComet(edgeId, stage?.color ?? '#8b5cf6')
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, events])

  function handleWheel(e: React.WheelEvent) {
    if (!e.ctrlKey && !e.metaKey) return // plain scroll: let the page scroll (SC-3)
    e.preventDefault()
    const delta = e.deltaY > 0 ? 0.92 : 1.08
    setTransform((t) => ({ ...t, scale: Math.min(3, Math.max(0.4, t.scale * delta)) }))
  }

  function handlePointerDown(e: React.PointerEvent) {
    if ((e.target as Element).closest('[data-node-button]')) return
    dragState.current = { x: transform.x, y: transform.y, startX: e.clientX, startY: e.clientY }
  }
  function handlePointerMove(e: React.PointerEvent) {
    if (!dragState.current) return
    const dx = e.clientX - dragState.current.startX
    const dy = e.clientY - dragState.current.startY
    setTransform((t) => ({ ...t, x: dragState.current!.x + dx, y: dragState.current!.y + dy }))
  }
  function handlePointerUp() {
    dragState.current = null
  }

  const pinnedData: NodeInfoCardData | null = useMemo(() => {
    const id = pinnedNode ?? hoveredNode
    if (!id) return null
    const node = mergedNodes[id]
    if (!node) return null
    const stats = nodeStats[id] ?? { status: 'idle', durationsMs: [], lastEventAt: null }
    return {
      id,
      label: node.label,
      purpose: node.purpose,
      modulePath: node.modulePath,
      status: stats.status,
      durationsMs: stats.durationsMs,
      lastEventAt: stats.lastEventAt,
      planned: node.planned,
    }
  }, [pinnedNode, hoveredNode, mergedNodes, nodeStats])

  const hoverLayout = pinnedData ? NODE_LAYOUT[pinnedData.id] : null

  return (
    <div className="theme-arch relative h-full w-full overflow-hidden rounded-lg border border-white/10 bg-black">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}`}
        className="h-full w-full"
        data-testid="architecture-canvas"
        data-current-edge={currentEdgeId ?? ''}
        data-edge-history={edgeHistory.join(',')}
        data-mode={mode}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        role="img"
        aria-label="System design diagram of the Veritas architecture"
      >
        <defs>
          <marker id="arch-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="#ffffff" />
          </marker>
        </defs>
        <rect x="0" y="0" width={CANVAS_WIDTH} height={CANVAS_HEIGHT} fill="#000000" />
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
          {GROUP_BOXES.map((box) => (
            <g key={box.id}>
              <rect
                x={box.x}
                y={box.y}
                width={box.width}
                height={box.height}
                rx={3}
                fill="var(--arch-surface-raised)"
                stroke="rgba(255,255,255,0.18)"
                strokeWidth={1.5}
              />
              <text x={box.x + 10} y={box.y + 20} fill="#ffffff" fontSize={13} fontWeight={600}>
                {box.title}
              </text>
            </g>
          ))}

          {EDGE_LAYOUT.map((edge) => {
            const isCurrent = edge.id === currentEdgeId
            return (
              <path
                key={edge.id}
                d={edgePathD(edge)}
                fill="none"
                stroke={isCurrent ? '#ffffff' : 'rgba(255,255,255,0.45)'}
                strokeWidth={isCurrent ? 2.2 : 1.5}
                markerEnd={edge.direction !== 'backward' ? 'url(#arch-arrow)' : undefined}
                markerStart={edge.direction === 'bidirectional' ? 'url(#arch-arrow)' : undefined}
                data-testid={`architecture-edge-${edge.id}`}
              />
            )
          })}
          {EDGE_LAYOUT.filter((e) => e.label).map((edge) => {
            const mid = edge.points[Math.floor(edge.points.length / 2)]
            return (
              <text key={`${edge.id}-label`} x={mid.x} y={mid.y - 8} fill="rgba(255,255,255,0.6)" fontSize={11} textAnchor="middle">
                {edge.label}
              </text>
            )
          })}

          {Object.keys(NODE_LAYOUT).map((nodeId) => {
            const layout = NODE_LAYOUT[nodeId]
            const node = mergedNodes[nodeId]
            const Icon = ARCH_ICON_BY_NODE[nodeId]
            const stats = nodeStats[nodeId]
            const half = layout.size / 2
            return (
              <g
                key={nodeId}
                ref={(el) => {
                  if (el) nodeRefs.current.set(nodeId, el)
                }}
                transform={`translate(${layout.x - half},${layout.y - half})`}
                data-testid={`architecture-node-${nodeId}`}
                data-node-button
                tabIndex={0}
                role="button"
                aria-label={`${node?.label ?? nodeId}: ${node?.purpose ?? ''}`}
                className="cursor-pointer outline-none focus-visible:[&>rect]:stroke-white"
                onMouseEnter={() => setHoveredNode(nodeId)}
                onMouseLeave={() => setHoveredNode((h) => (h === nodeId ? null : h))}
                onFocus={() => setHoveredNode(nodeId)}
                onBlur={() => setHoveredNode((h) => (h === nodeId ? null : h))}
                onClick={() => setPinnedNode((p) => (p === nodeId ? null : nodeId))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setPinnedNode((p) => (p === nodeId ? null : nodeId))
                  }
                }}
              >
                <rect
                  width={layout.size}
                  height={layout.size}
                  rx={10}
                  fill="transparent"
                  stroke={node?.planned ? 'rgba(255,255,255,0.3)' : 'transparent'}
                  strokeDasharray={node?.planned ? '4 3' : undefined}
                  strokeWidth={1.5}
                />
                {Icon && <Icon size={layout.size} />}
                {stats?.status === 'running' && !reduced && (
                  <circle cx={half} cy={half} r={half + 4} fill="none" stroke="#fbbf24" strokeWidth={2}>
                    <animate attributeName="r" values={`${half + 2};${half + 8};${half + 2}`} dur="1.4s" repeatCount="indefinite" />
                    <animate attributeName="opacity" values="0.8;0.1;0.8" dur="1.4s" repeatCount="indefinite" />
                  </circle>
                )}
                <text x={half} y={layout.size + 14} fill="#ffffff" fontSize={12} textAnchor="middle">
                  {node?.label ?? nodeId}
                </text>
              </g>
            )
          })}

          <g ref={cometLayerRef}>
            {comets.map((comet) => (
              <g key={comet.key} data-comet-key={comet.key}>
                <circle r={10} fill={comet.color} opacity={0.25} />
                <circle r={3.5} fill={comet.color} />
              </g>
            ))}
          </g>

          {showRobot && !reduced && (
            <g
              ref={robotRef}
              data-testid="architecture-robot"
              // Idle resting spot: the 'user' node, via the SAME offset-path mechanism
              // fireComet() later overwrites while animating — a plain `transform` here
              // would compose with offset-path ambiguously once an animation takes over.
              style={{
                offsetPath: `path("M ${NODE_LAYOUT.user.x - 24} ${NODE_LAYOUT.user.y + 10} L ${NODE_LAYOUT.user.x - 24} ${NODE_LAYOUT.user.y + 10}")`,
                offsetDistance: '0%',
              }}
            >
              <RobotCharacter state="walk" scale={0.4} />
            </g>
          )}
        </g>
      </svg>

      {hoverLayout && pinnedData && (
        <NodeInfoCard
          data={pinnedData}
          pinned={pinnedNode !== null}
          onClose={() => setPinnedNode(null)}
          style={{
            left: `${((hoverLayout.x + 40) / CANVAS_WIDTH) * 100}%`,
            top: `${((hoverLayout.y - 20) / CANVAS_HEIGHT) * 100}%`,
          }}
        />
      )}

      {/* Toolbar pill */}
      <div className="theme-arch pointer-events-none absolute top-3 right-3 flex items-center gap-1 rounded-full border border-white/10 bg-black/70 p-1 backdrop-blur">
        <button
          type="button"
          className="pointer-events-auto rounded-full p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
          aria-label="Fit view"
          onClick={() => setTransform({ x: 0, y: 0, scale: 1 })}
        >
          <Maximize2 className="size-4" />
        </button>
        <button
          type="button"
          className="pointer-events-auto rounded-full p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
          aria-label="Legend"
          aria-expanded={legendOpen}
          onClick={() => setLegendOpen((v) => !v)}
        >
          <Info className="size-4" />
        </button>
        <button
          type="button"
          className="pointer-events-auto rounded-full p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
          aria-label="Export SVG"
          onClick={() => svgRef.current && exportArchitectureSvg(svgRef.current)}
        >
          <Download className="size-4" />
        </button>
        <button
          type="button"
          className="pointer-events-auto rounded-full p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
          aria-label="Export PNG"
          onClick={() => svgRef.current && void exportArchitecturePng(svgRef.current)}
        >
          <ImageIcon className="size-4" />
        </button>
        <button
          type="button"
          className="pointer-events-auto rounded-full p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
          aria-label={showRobot ? 'Hide robot courier' : 'Show robot courier'}
          aria-pressed={showRobot}
          data-testid="toggle-robot"
          onClick={() => setShowRobot((v) => !v)}
        >
          <Bot className="size-4" />
        </button>
        <div className="pointer-events-auto ml-1 flex gap-1 rounded-full bg-white/5 p-0.5">
          {(['tour', 'live'] as const).map((m) => (
            <button
              key={m}
              type="button"
              data-testid={`light-flow-mode-${m}`}
              onClick={() => onModeChange(m)}
              className={cn(
                'rounded-full px-2 py-1 text-[11px] font-medium capitalize',
                mode === m ? 'bg-white/20 text-white' : 'text-white/50',
              )}
            >
              {m === 'tour' ? 'Demo flow' : 'Live'}
            </button>
          ))}
        </div>
      </div>

      {legendOpen && (
        <div
          className="theme-arch absolute top-14 right-3 w-56 rounded-lg border border-[color:var(--arch-border)] bg-[color:var(--arch-surface)] p-3 text-[11px] text-white/80 shadow-xl"
          data-testid="architecture-legend"
        >
          <p className="mb-1.5 font-semibold text-white">Legend</p>
          <ul className="flex flex-col gap-1">
            {LIGHT_FLOW_STAGES.map((s) => (
              <li key={s.id} className="flex items-center gap-2">
                <span className="size-2.5 rounded-full" style={{ background: s.color }} />
                Stage {s.id} &middot; {s.name}
              </li>
            ))}
            <li className="mt-1 flex items-center gap-2">
              <span className="h-0 w-4 border-t border-dashed border-white/40" />
              Planned, not yet real
            </li>
          </ul>
        </div>
      )}

      <div className="theme-arch absolute top-3 left-3 flex items-center gap-2 rounded-full border border-white/10 bg-black/70 px-3 py-1.5 text-xs text-white/80 backdrop-blur">
        <span className={cn('size-2 rounded-full', connected ? 'bg-[color:var(--color-success)]' : 'bg-white/30')} />
        {connected ? 'live' : 'disconnected'}
      </div>

      <button
        type="button"
        className="theme-arch pointer-events-auto absolute bottom-24 left-3 rounded-full border border-white/10 bg-black/70 p-2 text-white/60 hover:text-white md:hidden"
        aria-label="Toggle legend"
        onClick={() => setShowInfoPopover((v) => !v)}
      >
        <Info className="size-4" />
      </button>
      {showInfoPopover && <span className="sr-only">Legend toggled</span>}

      <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2">
        <LightFlowDock
          mode={mode}
          activeStageId={activeStage.id}
          playing={playing}
          speed={speed}
          onPlayPause={() => setPlaying((p) => !p)}
          onPrev={() => {
            tourEpoch.current++
            setCurrentEdgeId(null)
            setTourStageIndex((i) => (i - 1 + LIGHT_FLOW_STAGES.length) % LIGHT_FLOW_STAGES.length)
            setTourEdgeIndex(0)
          }}
          onNext={() => {
            tourEpoch.current++
            setCurrentEdgeId(null)
            setTourStageIndex((i) => (i + 1) % LIGHT_FLOW_STAGES.length)
            setTourEdgeIndex(0)
          }}
          onSpeedChange={setSpeed}
          onSelectStage={(id) => {
            tourEpoch.current++
            // Clearing this synchronously (not left to the next fireComet call) means a test
            // or viewer watching data-current-edge never sees a stale leftover value from
            // whatever edge was mid-flight the instant before this jump.
            setCurrentEdgeId(null)
            setTourStageIndex(LIGHT_FLOW_STAGES.findIndex((s) => s.id === id))
            setTourEdgeIndex(0)
          }}
        />
      </div>
    </div>
  )
}
