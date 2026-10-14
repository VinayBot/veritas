import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { toast } from 'sonner'
import { Download, Play, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Segmented } from '@/components/ui/segmented'
import { ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useCommands, type CommandPaletteItem } from '@/components/ui/command-palette'
import { ArchitectureCanvas } from '@/components/architecture/ArchitectureCanvas'
import { HealthStrip } from '@/components/architecture/HealthStrip'
import { NodeDrawer } from '@/components/architecture/NodeDrawer'
import { TraceDock } from '@/components/architecture/TraceDock'
import { exportArchitectureJson, exportArchitecturePng, exportArchitectureSvg } from '@/components/architecture/architectureExport'
import { cancelAllPackets, emitPacket, packetsDrawn } from '@/components/architecture/packets'
import type { Scene, StageSummary, ViewMode } from '@/components/architecture/scene'
import { hopFor, isLive, nodeActivity, packetDurationMs, type NodeActivity } from '@/components/architecture/trace'
import { usePolling } from '@/hooks/usePolling'
import { useTraceEvents } from '@/hooks/useTraceEvents'
import { getArchitectureGraph, getSubsystems } from '@/lib/api/client'
import type { ArchitectureGraph, TraceEvent } from '@/lib/api/types'
import { relativeTime } from '@/lib/format'
import { useAppStore } from '@/store/app-store'

const eventKey = (e: TraceEvent) => `${e.session_id}:${e.seq}`

const LEGEND = [
  { label: 'request', className: 'bg-accent' },
  { label: 'data', className: 'bg-muted' },
  { label: 'trace', className: 'bg-live' },
  { label: 'optional', className: 'border border-dashed border-muted bg-transparent' },
]

export function ArchitecturePage() {
  const { documentId, sessionId } = useAppStore()
  const [view, setView] = useState<ViewMode>('overview')
  const [socketEnabled, setSocketEnabled] = useState(true)
  const [follow, setFollow] = useState(true)
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null)
  const [dismissedErrors, setDismissedErrors] = useState<Set<string>>(new Set())
  const [replayEvents, setReplayEvents] = useState<TraceEvent[] | null>(null)
  const reduced = useReducedMotion()
  const sceneRef = useRef<Scene | null>(null)
  const [sceneReady, setSceneReady] = useState(false)
  const seenRef = useRef<Set<string>>(new Set())
  const [tour, setTour] = useState<{ active: string[]; done: string[] } | null>(null)
  const tourTimers = useRef<number[]>([])

  const graphPoll = usePolling(getArchitectureGraph, { intervalMs: 15_000 })
  const healthPoll = usePolling(() => getSubsystems(), { intervalMs: 15_000 })
  const graph: ArchitectureGraph | null = graphPoll.data

  const ingestion = useTraceEvents(documentId, { enabled: socketEnabled })
  const chat = useTraceEvents(sessionId, { enabled: socketEnabled })

  const liveEvents = useMemo(
    () => [...ingestion.events, ...chat.events].sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at) || a.seq - b.seq),
    [ingestion.events, chat.events],
  )

  const watched = [documentId ? ingestion.socket : null, sessionId ? chat.socket : null].filter((s): s is NonNullable<typeof s> => s !== null)
  const socketOpen = watched.length > 0 && watched.every((s) => s === 'open')
  const overall: 'live' | 'connecting' | 'disconnected' | 'idle' | 'replay' =
    replayEvents !== null
      ? 'replay'
      : watched.length === 0
        ? 'idle'
        : socketOpen
          ? 'live'
          : watched.some((s) => s === 'closed')
            ? 'disconnected'
            : 'connecting'

  const shownEvents = replayEvents ?? liveEvents
  const animating = overall === 'live' || overall === 'replay'

  // The moment the socket is not open, everything in flight stops.
  useEffect(() => {
    if (!animating) cancelAllPackets()
  }, [animating])

  /** Draws the hop an event stands for. "pending" means there is a hop but its edge is not
   * on screen yet (the view is still being built), so the caller should try again. */
  const fire = useCallback(
    (event: TraceEvent, earlier: TraceEvent[]): 'none' | 'drawn' | 'pending' => {
      const scene = sceneRef.current
      // Reduced motion: the event is still listed and the node still changes state; only
      // the travelling packet is skipped.
      if (!graph || !scene || reduced) return 'none'
      const hop = hopFor(event, earlier, graph)
      if (!hop) return 'none'
      const edges = hop.edgeIds.map((id) => scene.edgeFor[id]).filter((id, i, all): id is string => !!id && all.indexOf(id) === i)
      if (edges.length === 0) return 'none'
      const perEdge = packetDurationMs(hop.measuredMs) / edges.length
      const drawn = edges.map((edgeId, i) => {
        const kind = scene.edges.find((e) => e.id === edgeId)?.kind ?? 'data'
        return emitPacket(edgeId, { durationMs: perEdge, delayMs: i * perEdge, kind })
      })
      return drawn.some(Boolean) ? 'drawn' : 'pending'
    },
    [graph, reduced],
  )

  // One packet per real hop, only for events that are happening now.
  const [retryTick, setRetryTick] = useState(0)
  useEffect(() => {
    // Wait until there is a diagram to draw on; otherwise early events would be marked as
    // handled without ever being shown.
    if (replayEvents !== null || !graph || !sceneRef.current) return
    let pending = false
    for (const event of liveEvents) {
      const key = eventKey(event)
      if (seenRef.current.has(key)) continue
      if (!isLive(event)) {
        seenRef.current.add(key) // history: shown as state, never animated
        continue
      }
      // A live event that arrives before the socket is reported open is left for the next
      // pass rather than dropped.
      if (!socketOpen) continue
      // So is one whose edge is not drawn yet, which happens when the view was opened or
      // switched a moment ago. It is retried until it is drawn or stops being current.
      if (fire(event, liveEvents) === 'pending') pending = true
      else seenRef.current.add(key)
    }
    if (!pending) return
    const timer = window.setTimeout(() => setRetryTick((n) => n + 1), 250)
    return () => window.clearTimeout(timer)
  }, [liveEvents, socketOpen, fire, replayEvents, graph, sceneReady, retryTick])

  const activity = useMemo(() => {
    if (!graph) return {}
    const raw = nodeActivity(shownEvents, graph.stage_to_node)
    if (tour) {
      // The walkthrough owns the diagram while it plays, so it is never mistaken for traffic.
      return Object.fromEntries([...tour.done.map((id) => [id, 'done']), ...tour.active.map((id) => [id, 'active'])]) as Record<string, NodeActivity>
    }
    if (animating) return raw
    // Disconnected: what finished is still a fact, but "running" can no longer be claimed.
    return Object.fromEntries(Object.entries(raw).map(([id, state]) => [id, state === 'active' ? 'idle' : state])) as Record<string, NodeActivity>
  }, [shownEvents, graph, animating, tour])

  const stickyErrors = useMemo(() => {
    if (!graph) return new Set<string>()
    const ids = new Set<string>()
    for (const event of shownEvents) {
      if (event.status !== 'error' || dismissedErrors.has(eventKey(event))) continue
      const node = graph.stage_to_node[event.stage]
      if (node) ids.add(node)
    }
    return ids
  }, [shownEvents, graph, dismissedErrors])

  const focusNodeId = useMemo(() => {
    if (!graph || !animating) return null
    const running = [...shownEvents].reverse().find((e) => e.status === 'running')
    return running ? (graph.stage_to_node[running.stage] ?? null) : null
  }, [shownEvents, graph, animating])

  // A new trace starting re-enables follow, as the brief asks; panning cancels it again.
  const firstSeq = shownEvents[0] ? eventKey(shownEvents[0]) : null
  useEffect(() => {
    if (view === 'live') setFollow(true)
  }, [firstSeq, view])

  const replayTimers = useRef<number[]>([])
  const stopReplay = useCallback(() => {
    replayTimers.current.forEach((t) => window.clearTimeout(t))
    replayTimers.current = []
    cancelAllPackets()
    setReplayEvents(null)
  }, [])
  useEffect(() => stopReplay, [stopReplay])

  /** Re-plays the most recent recorded session with its real gaps (long waits shortened).
   * It is labelled a replay; it is never started automatically. */
  function handleReplay() {
    const source = chat.events.length > 0 ? chat.events : ingestion.events
    if (source.length === 0) return
    stopReplay()
    const ordered = [...source].sort((a, b) => a.seq - b.seq)
    setReplayEvents([])
    let at = 0
    ordered.forEach((event, i) => {
      if (i > 0) {
        const gap = Date.parse(event.started_at) + (event.duration_ms ?? 0) - (Date.parse(ordered[i - 1].started_at) + (ordered[i - 1].duration_ms ?? 0))
        at += Math.max(120, Math.min(1800, gap))
      }
      replayTimers.current.push(
        window.setTimeout(() => {
          setReplayEvents((prev) => [...(prev ?? []), event])
          fire(event, ordered.slice(0, i))
        }, at),
      )
    })
    replayTimers.current.push(window.setTimeout(() => setReplayEvents(null), at + 2500))
  }

  const stopTour = useCallback(() => {
    tourTimers.current.forEach((t) => window.clearTimeout(t))
    tourTimers.current = []
    setTour(null)
  }, [])
  useEffect(() => stopTour, [stopTour])

  /** Walks the declared request path outward from the browser, one hop at a time. This is an
   * illustration of how a question travels, started by hand and labelled as such. */
  function handleTour() {
    const scene = sceneRef.current
    const start = graph?.stage_to_node.client
    if (!graph || !scene || !start) return
    stopTour()
    stopReplay()
    const levels: { nodes: string[]; edges: string[] }[] = []
    const seen = new Set([start])
    let frontier = [start]
    while (frontier.length > 0 && levels.length < 12) {
      const hops = graph.edges.filter((e) => e.kind === 'request' && frontier.includes(e.source) && !seen.has(e.target))
      if (hops.length === 0) break
      const nodes = [...new Set(hops.map((e) => e.target))]
      nodes.forEach((id) => seen.add(id))
      levels.push({ nodes, edges: hops.map((e) => e.id) })
      frontier = nodes
    }
    const STEP_MS = 720
    setTour({ active: [start], done: [] })
    levels.forEach((level, i) => {
      tourTimers.current.push(
        window.setTimeout(() => {
          if (!reduced) {
            const sceneEdges = [...new Set(level.edges.map((id) => scene.edgeFor[id]).filter(Boolean))]
            // A short stream of three packets per hop rather than a single dot.
            sceneEdges.forEach((edgeId) => [0, 130, 260].forEach((delayMs) => emitPacket(edgeId, { durationMs: STEP_MS - 120, delayMs, kind: 'request' })))
          }
          tourTimers.current.push(
            window.setTimeout(() => setTour((prev) => (prev ? { active: level.nodes, done: [...prev.done, ...prev.active] } : prev)), reduced ? 0 : STEP_MS - 120),
          )
        }, i * STEP_MS),
      )
    })
    tourTimers.current.push(window.setTimeout(stopTour, levels.length * STEP_MS + 1600))
  }

  const selectedScene = selectedSceneId ? sceneRef.current?.nodes.find((n) => n.id === selectedSceneId) : undefined
  const selectedNode = selectedSceneId && graph ? (graph.nodes.find((n) => n.id === selectedSceneId) ?? null) : null
  const selectedSummary: StageSummary | null = selectedScene?.summary ?? null

  const commands = useMemo<CommandPaletteItem[]>(
    () => [
      { id: 'run-self-check', label: 'Run self-check', group: 'Run', keywords: 'health diagnose', onSelect: () => window.dispatchEvent(new Event('veritas:self-check')) },
      { id: 'arch-overview', label: 'Architecture: Overview', group: 'View', onSelect: () => setView('overview') },
      { id: 'arch-detailed', label: 'Architecture: Detailed', group: 'View', onSelect: () => setView('detailed') },
      { id: 'arch-live', label: 'Architecture: Live Trace', group: 'View', onSelect: () => setView('live') },
    ],
    [],
  )
  useCommands('architecture', commands)

  async function handleExport(kind: 'png' | 'svg' | 'json') {
    try {
      if (kind === 'json') {
        if (graph) exportArchitectureJson(graph)
      } else if (sceneRef.current) {
        if (kind === 'svg') exportArchitectureSvg(sceneRef.current)
        else await exportArchitecturePng(sceneRef.current)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Export failed')
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-6" data-testid="architecture-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="blade-edge font-display text-2xl font-semibold tracking-tight text-foreground">Architecture</h1>
          <p className="mt-3 max-w-3xl text-sm text-muted-foreground">
            Drawn from the running backend: modules are discovered from the code, the agent’s nodes and edges are read off the compiled LangGraph, and
            status comes from live probes.
            {graphPoll.updatedAt && <span className="ml-1">Refreshed {relativeTime(graphPoll.updatedAt)}.</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            label="Diagram view"
            value={view}
            onChange={setView}
            testIdPrefix="view-mode"
            options={[
              { value: 'overview', label: 'Overview' },
              { value: 'detailed', label: 'Detailed' },
              { value: 'live', label: 'Live Trace' },
            ]}
          />
          <Button variant={tour ? 'default' : 'outline'} size="sm" disabled={!graph} onClick={tour ? stopTour : handleTour} data-testid="play-request-path">
            {tour ? <Square className="size-3.5" /> : <Play className="size-3.5" />}
            {tour ? 'Stop walkthrough' : 'Play request path'}
          </Button>
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" disabled={!graph} data-testid="export-menu">
                <Download className="size-3.5" /> Export
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-56 p-2">
              <div className="flex flex-col">
                {(
                  [
                    ['png', 'PNG image'],
                    ['svg', 'SVG image'],
                    ['json', 'JSON (the topology payload)'],
                  ] as const
                ).map(([kind, label]) => (
                  <button
                    key={kind}
                    type="button"
                    data-testid={`export-${kind}`}
                    onClick={() => void handleExport(kind)}
                    className="rounded-lg px-3 py-2 text-left text-sm text-foreground transition-colors duration-micro hover:bg-surface-raised"
                  >
                    {label}
                  </button>
                ))}
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </header>

      <HealthStrip
        subsystems={healthPoll.data?.subsystems ?? null}
        error={healthPoll.error}
        traceSocket={{ state: watched.length === 0 ? 'idle' : socketOpen ? 'open' : watched.some((s) => s === 'closed') ? 'closed' : 'connecting', watching: watched.length }}
        onChecked={() => {
          healthPoll.refresh()
          graphPoll.refresh()
        }}
      />

      <div className="flex min-h-0 flex-1 gap-4">
        <div className="relative min-w-0 flex-1 overflow-hidden rounded-xl border border-border bg-background">
          <div className="arch-grid" aria-hidden="true" />
          <div className="aurora" aria-hidden="true">
            <span />
            <span />
          </div>
          {/* Re-keyed so the sweep replays when the view changes or a walkthrough starts. */}
          {graph !== null && !reduced && <div key={`${view}-${tour ? 'tour' : 'idle'}`} className="scan-sweep" aria-hidden="true" />}
          {tour && (
            <p className="absolute top-3 left-1/2 z-(--z-raised) -translate-x-1/2 rounded-pill border border-gold/40 bg-surface/90 px-3 py-1 text-xs text-accent-soft backdrop-blur" role="status" data-testid="tour-banner">
              Walkthrough of the declared request path — an illustration, not live traffic
            </p>
          )}
          {graphPoll.error !== null && graph === null ? (
            <div className="flex h-full items-center justify-center">
              <ErrorState error={graphPoll.error} action={<Button size="sm" variant="outline" onClick={graphPoll.refresh}>Retry</Button>} />
            </div>
          ) : graph === null ? (
            <LoadingState shape="graph" label="Loading the architecture" className="h-full" />
          ) : (
            <ArchitectureCanvas
              graph={graph}
              view={view}
              activity={activity}
              stickyErrors={stickyErrors}
              selectedId={selectedSceneId}
              onSelect={setSelectedSceneId}
              focusNodeId={view === 'live' ? focusNodeId : null}
              follow={follow}
              onUserMove={() => setFollow(false)}
              onScene={(scene) => {
                sceneRef.current = scene
                setSceneReady(true)
              }}
            />
          )}
          <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface/90 px-3 py-1.5 text-[11px] text-muted-foreground" data-testid="architecture-legend">
            {LEGEND.map((item) => (
              <span key={item.label} className="flex items-center gap-1.5">
                <span className={`inline-block h-0.5 w-5 rounded-full ${item.className}`} aria-hidden="true" />
                {item.label}
              </span>
            ))}
            <span title="Faint drifting dashes only show which way an edge flows. A bright packet is a real trace event.">· drifting dashes = direction, bright packets = real events</span>
          </div>
        </div>

        {view === 'live' && graph && (
          <TraceDock
            sources={[
              { label: 'Ingestion', sessionId: documentId, socket: ingestion.socket },
              { label: 'Chat', sessionId, socket: chat.socket },
            ]}
            events={shownEvents}
            overall={overall}
            follow={follow}
            onToggleFollow={() => setFollow((v) => !v)}
            socketEnabled={socketEnabled}
            onToggleSocket={() => setSocketEnabled((v) => !v)}
            replaying={replayEvents !== null}
            onReplay={handleReplay}
            canReplay={liveEvents.length > 0}
            hasErrors={stickyErrors.size > 0}
            onClearErrors={() => setDismissedErrors(new Set(shownEvents.filter((e) => e.status === 'error').map(eventKey)))}
            pulsesDrawn={packetsDrawn()}
            stageToNode={graph.stage_to_node}
            onSelectNode={setSelectedSceneId}
          />
        )}
      </div>

      <NodeDrawer
        node={selectedNode}
        summary={selectedSummary}
        statsSince={graph?.stats_since ?? ''}
        onClose={() => setSelectedSceneId(null)}
        onOpenModule={(id) => {
          setView('detailed')
          setSelectedSceneId(id)
        }}
      />
    </div>
  )
}
