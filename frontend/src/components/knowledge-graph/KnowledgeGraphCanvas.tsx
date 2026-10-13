import { useMemo, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import ForceGraph2D from 'react-force-graph-2d'
import type { GraphEdge, GraphNode } from '@/lib/api/types'
import { ParticleTorusScene } from './ParticleTorusScene'
import { buildEntityPoints, type EntityPoint } from './knowledgeGraphLayout'

const INITIAL_FIELD_COUNT = 10_000
const MIN_FIELD_COUNT = 1_500

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return !!(canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
  } catch {
    return false
  }
}

export interface KnowledgeGraphCanvasProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  onSelectEntity: (entity: EntityPoint | null) => void
  highlightSequence?: string[]
  onHighlightStep?: (entityId: string) => void
}

export function KnowledgeGraphCanvas({
  nodes,
  edges,
  onSelectEntity,
  highlightSequence,
  onHighlightStep,
}: KnowledgeGraphCanvasProps) {
  const reduced = useReducedMotion()
  const [fieldCount, setFieldCount] = useState(INITIAL_FIELD_COUNT)
  const [hover, setHover] = useState<{ entity: EntityPoint; x: number; y: number } | null>(null)
  const webglAvailable = useMemo(() => hasWebGL(), [])

  const entities = useMemo(() => buildEntityPoints(nodes, edges), [nodes, edges])
  const communityCount = useMemo(
    () => new Set(nodes.map((n) => n.community).filter((c): c is number => c !== null && c !== undefined)).size,
    [nodes],
  )

  if (!webglAvailable) {
    // KG-7: no WebGL -> fall back to the pre-existing 2D force graph rather than a blank page.
    return (
      <ForceGraph2D
        graphData={{
          nodes: nodes.map((n) => ({ ...n })),
          links: edges.map((e) => ({ source: e.source, target: e.target, predicate: e.predicate })),
        }}
        nodeId="id"
        nodeLabel={(n) => `${(n as GraphNode).name} (${(n as GraphNode).label})`}
        nodeColor={(n) => {
          const community = (n as GraphNode).community
          return community === null || community === undefined ? '#8d8aa3' : '#8b5cf6'
        }}
        backgroundColor="transparent"
        onNodeClick={(n) => onSelectEntity(entities.find((e) => e.id === (n as GraphNode).id) ?? null)}
      />
    )
  }

  return (
    <div className="relative h-full w-full bg-black">
      <ParticleTorusScene
        entities={entities}
        edges={edges}
        fieldCount={fieldCount}
        reducedMotion={!!reduced}
        onHoverEntity={(entity, pos) => setHover(entity && pos ? { entity, x: pos.x, y: pos.y } : null)}
        onClickEntity={onSelectEntity}
        onLowFps={() => setFieldCount((c) => Math.max(MIN_FIELD_COUNT, Math.floor(c / 2)))}
        highlightSequence={highlightSequence}
        onHighlightStep={onHighlightStep}
      />

      {hover && (
        <div
          className="pointer-events-none absolute z-10 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs shadow-lg"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
          data-testid="knowledge-graph-tooltip"
        >
          <p className="font-medium text-foreground">{hover.entity.name}</p>
          <p className="text-muted-foreground">
            {hover.entity.label} &middot; degree {hover.entity.degree}
            {hover.entity.community >= 0 && <> &middot; community {hover.entity.community}</>}
          </p>
        </div>
      )}

      <div
        className="pointer-events-none absolute bottom-3 left-3 flex gap-2 text-xs"
        data-testid="knowledge-graph-stats"
      >
        <span className="rounded-full border border-border bg-surface/90 px-2.5 py-1 backdrop-blur">
          Entities: {nodes.length}
        </span>
        <span className="rounded-full border border-border bg-surface/90 px-2.5 py-1 backdrop-blur">
          Relations: {edges.length}
        </span>
        <span className="rounded-full border border-border bg-surface/90 px-2.5 py-1 backdrop-blur">
          Communities: {communityCount}
        </span>
      </div>
    </div>
  )
}
