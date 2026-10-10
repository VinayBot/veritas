import { useEffect, useMemo, useState } from 'react'
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  useReactFlow,
  type Node,
  type Edge,
  Handle,
  Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { motion, useReducedMotion } from 'framer-motion'
import { useAppStore } from '@/store/app-store'
import { useTraceEvents } from '@/hooks/useTraceEvents'
import { StateMessage } from '@/components/ui/state-message'
import { JourneyView, type CheckpointDef } from '@/components/architecture/journey-view'
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
} from '@/components/ui/drawer'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { TraceEvent, TraceStatus } from '@/lib/api/types'

const INGESTION_LANE: { id: string; label: string }[] = [
  { id: 'upload', label: 'Upload' },
  { id: 'parse', label: 'Parse' },
  { id: 'refine', label: 'Refine' },
  { id: 'pii_vault', label: 'PII Vault' },
  { id: 'chunk', label: 'Chunk' },
  { id: 'embed', label: 'Embed' },
  { id: 'index', label: 'Index' },
  { id: 'graph', label: 'Graph' },
  { id: 'profile', label: 'Profile' },
  { id: 'advisor', label: 'Advisor' },
]

const CHAT_LANE: { id: string; label: string }[] = [
  { id: 'guardian_in', label: 'Guardian In' },
  { id: 'semantic_cache', label: 'Semantic Cache' },
  { id: 'planner', label: 'Planner' },
  { id: 'rewriter', label: 'Rewriter' },
  { id: 'retriever', label: 'Retriever' },
  { id: 'critic', label: 'Critic' },
  { id: 'synthesizer', label: 'Synthesizer' },
  { id: 'verifier', label: 'Verifier' },
  { id: 'guardian_out', label: 'Guardian Out' },
]

const STATUS_COLOR: Record<TraceStatus | 'idle', string> = {
  idle: 'border-border bg-surface-raised text-muted-foreground',
  queued: 'border-warning/40 bg-warning/10 text-warning',
  running: 'border-accent bg-accent/15 text-accent-soft',
  done: 'border-success/50 bg-success/10 text-success',
  blocked: 'border-danger/50 bg-danger/10 text-danger',
  error: 'border-danger/50 bg-danger/10 text-danger',
  retrying: 'border-warning/50 bg-warning/15 text-warning',
}

interface StageNodeData {
  label: string
  status: TraceStatus | 'idle'
  onClick: () => void
}

function StageNode({ data }: { data: StageNodeData }) {
  const reduced = useReducedMotion()
  const isActive = data.status === 'running' && !reduced
  return (
    <motion.button
      type="button"
      onClick={data.onClick}
      className={cn(
        'rounded-lg border-2 px-4 py-3 text-xs font-medium shadow-sm transition-colors',
        STATUS_COLOR[data.status],
      )}
      animate={isActive ? { scale: [1, 1.06, 1] } : { scale: 1 }}
      transition={isActive ? { duration: 1.1, repeat: Infinity } : { duration: 0.2 }}
    >
      <Handle type="target" position={Position.Left} className="!bg-border" />
      {data.label}
      <Handle type="source" position={Position.Right} className="!bg-border" />
    </motion.button>
  )
}

const nodeTypes = { stage: StageNode }

/** The declarative `fitView` prop only runs once, on ReactFlow's initial mount — if that
 * happens before the parent flex layout has settled a real width/height (routinely true on a
 * client-side route change, where there's no network wait to accidentally cover for it), it
 * fits against a zero-size viewport and the nodes end up positioned off-screen with nothing
 * to correct them afterward. Re-fitting imperatively whenever the node count actually changes
 * (mount, and the 0 -> N transition once a session's nodes exist) fixes that for real, rather
 * than papering over it with a longer arbitrary delay. */
function FitViewOnChange({ nodeCount }: { nodeCount: number }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    if (nodeCount === 0) return
    const raf = requestAnimationFrame(() => fitView({ duration: 200 }))
    return () => cancelAnimationFrame(raf)
  }, [nodeCount, fitView])
  return null
}

function laneToFlow(
  lane: { id: string; label: string }[],
  events: TraceEvent[],
  row: number,
  onSelect: (stage: string, event: TraceEvent | null) => void,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = lane.map((stage, i) => {
    const matching = events.filter((e) => e.stage === stage.id)
    const latest = matching[matching.length - 1]
    return {
      id: stage.id,
      type: 'stage',
      position: { x: i * 190, y: row * 120 },
      data: {
        label: stage.label,
        status: latest?.status ?? 'idle',
        onClick: () => onSelect(stage.id, latest ?? null),
      } satisfies StageNodeData,
    }
  })
  const edges: Edge[] = lane.slice(1).map((stage, i) => ({
    id: `${lane[i].id}->${stage.id}`,
    source: lane[i].id,
    target: stage.id,
    animated: events.some((e) => e.from_stage === lane[i].id && e.to_stage === stage.id),
    style: { stroke: 'var(--color-border)' },
  }))
  return { nodes, edges }
}

export function ArchitecturePage() {
  const { documentId, documentName, sessionId } = useAppStore()
  const [source, setSource] = useState<'ingestion' | 'chat'>('ingestion')
  const [viewMode, setViewMode] = useState<'journey' | 'detailed'>('journey')
  const traceSessionId = source === 'ingestion' ? documentId : sessionId
  const { events, connected } = useTraceEvents(traceSessionId)
  // The Journey view spans the whole ingest -> query lifecycle (checkpoints 1-3 are
  // ingestion, 4-5 are chat), so unlike Detailed (which only ever shows one lane) it needs
  // both event streams at once regardless of which `source` toggle Detailed has selected.
  const { events: ingestionEventsForJourney } = useTraceEvents(viewMode === 'journey' ? documentId : null)
  const { events: chatEventsForJourney } = useTraceEvents(viewMode === 'journey' ? sessionId : null)
  const [selected, setSelected] = useState<{ stage: string; event: TraceEvent | null } | null>(
    null,
  )

  const { nodes, edges } = useMemo(() => {
    const lane = source === 'ingestion' ? INGESTION_LANE : CHAT_LANE
    return laneToFlow(lane, events, 0, (stage, event) => setSelected({ stage, event }))
  }, [source, events])

  function selectCheckpoint(cp: CheckpointDef) {
    const events = cp.source === 'ingestion' ? ingestionEventsForJourney : chatEventsForJourney
    const latestPerStage = cp.stages
      .map((stageId) => {
        const matching = events.filter((e) => e.stage === stageId)
        return matching[matching.length - 1] ?? null
      })
      .filter((e): e is TraceEvent => e !== null)
    const mostRecent = latestPerStage.sort((a, b) => b.seq - a.seq)[0] ?? null
    setSelected({ stage: cp.label, event: mostRecent })
  }

  if (!documentId) {
    return (
      <div className="flex h-screen items-center justify-center p-6">
        <StateMessage status="empty" description="Upload a document in Workspace first." />
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col gap-4 p-6">
      <header className="flex items-center justify-between gap-2">
        <div>
          <h1 className="font-display text-2xl font-semibold text-foreground">Architecture</h1>
          <p className="text-sm text-muted-foreground">
            Every pulse here is a real event from{' '}
            <code className="text-xs">/ws/trace/{traceSessionId ?? '...'}</code> — nothing is
            timer-driven.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={connected ? 'success' : 'outline'}>
            {connected ? 'live' : 'disconnected'}
          </Badge>
          <div className="flex gap-1 rounded-full bg-surface-raised p-1">
            {(['journey', 'detailed'] as const).map((v) => (
              <button
                key={v}
                onClick={() => setViewMode(v)}
                data-testid={`view-mode-${v}`}
                className={cn(
                  'rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors',
                  viewMode === v ? 'bg-accent text-on-accent' : 'text-muted-foreground',
                )}
              >
                {v}
              </button>
            ))}
          </div>
          {viewMode === 'detailed' && (
            <div className="flex gap-1 rounded-full bg-surface-raised p-1">
              {(['ingestion', 'chat'] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setSource(s)}
                  className={cn(
                    'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                    source === s ? 'bg-accent text-on-accent' : 'text-muted-foreground',
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      {viewMode === 'journey' && (
        <div className="flex-1">
          <JourneyView
            ingestionEvents={ingestionEventsForJourney}
            chatEvents={chatEventsForJourney}
            fileLabel={documentName}
            onSelectCheckpoint={selectCheckpoint}
          />
        </div>
      )}

      {viewMode === 'detailed' && source === 'chat' && !sessionId && (
        <StateMessage
          status="empty"
          description="Send a chat message in Workspace first to see the agentic pipeline run."
        />
      )}

      {viewMode === 'detailed' && (
        <div className="flex-1 rounded-lg border border-border bg-surface">
          <ReactFlowProvider>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              proOptions={{ hideAttribution: true }}
              nodesDraggable={false}
              nodesConnectable={false}
            >
              <Background />
              <FitViewOnChange nodeCount={nodes.length} />
            </ReactFlow>
          </ReactFlowProvider>
        </div>
      )}

      <Drawer open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DrawerContent>
          {selected && (
            <>
              <DrawerHeader>
                <DrawerTitle>{selected.stage}</DrawerTitle>
                <DrawerDescription>
                  {selected.event ? `status: ${selected.event.status}` : 'Not run yet'}
                </DrawerDescription>
              </DrawerHeader>
              {selected.event ? (
                <div className="flex flex-col gap-3 text-sm">
                  {selected.event.duration_ms !== null && (
                    <p className="text-muted-foreground">
                      Duration: {selected.event.duration_ms.toFixed(0)}ms
                    </p>
                  )}
                  {selected.event.output_preview && (
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Output</p>
                      <p className="rounded-md bg-surface-raised p-2 text-xs">
                        {selected.event.output_preview}
                      </p>
                    </div>
                  )}
                  {Object.keys(selected.event.metrics).length > 0 && (
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Metrics</p>
                      <pre className="overflow-x-auto rounded-md bg-surface-raised p-2 text-xs">
                        {JSON.stringify(selected.event.metrics, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No trace event for this stage yet in the current session.
                </p>
              )}
            </>
          )}
        </DrawerContent>
      </Drawer>
    </div>
  )
}
