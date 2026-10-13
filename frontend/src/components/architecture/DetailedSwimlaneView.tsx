import { useEffect } from 'react'
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
import { cn } from '@/lib/utils'
import type { TraceEvent, TraceStatus } from '@/lib/api/types'

/** The pre-existing per-lane swimlane graph (AR-1: "the existing Detailed (swimlane) mode
 * stays"). Pulled into its own module so @xyflow/react — one of the heaviest deps in this
 * app (see component-showcase.tsx's own lazy-loading of it for the same reason) — only loads
 * once a viewer actually switches to Detailed, instead of on every Architecture page visit
 * (System Design, now the default, is plain SVG and needs none of it). */

export const INGESTION_LANE: { id: string; label: string }[] = [
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

export const CHAT_LANE: { id: string; label: string }[] = [
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

export interface DetailedSwimlaneViewProps {
  source: 'ingestion' | 'chat'
  events: TraceEvent[]
  onSelectStage: (stage: string, event: TraceEvent | null) => void
}

export function DetailedSwimlaneView({ source, events, onSelectStage }: DetailedSwimlaneViewProps) {
  const lane = source === 'ingestion' ? INGESTION_LANE : CHAT_LANE
  const { nodes, edges } = laneToFlow(lane, events, 0, onSelectStage)

  return (
    <div className="h-full w-full">
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
  )
}
