import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useReducedMotion } from 'framer-motion'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ArchitectureGraph } from '@/lib/api/types'
import { FlowEdge, type FlowEdgeData } from './FlowEdge'
import { ChildNode, GroupNode, LaneNode, ModuleNode, StageNode, type CanvasNodeData } from './nodes'
import { buildScene, type Scene, type ViewMode } from './scene'
import type { NodeActivity } from './trace'

// "cluster", not "group": xyflow ships default styling for a node type named group.
const NODE_TYPES = { module: ModuleNode, child: ChildNode, cluster: GroupNode, stage: StageNode, lane: LaneNode }
const EDGE_TYPES = { flow: FlowEdge }

/** Everything reachable from or leading to `id` in this scene, plus group members. */
function connectedInScene(id: string, scene: Scene): Set<string> {
  const walk = (direction: 'down' | 'up') => {
    const seen = new Set<string>([id])
    const queue = [id]
    while (queue.length > 0) {
      const current = queue.shift()!
      for (const e of scene.edges) {
        const from = direction === 'down' ? e.source : e.target
        const to = direction === 'down' ? e.target : e.source
        if (from === current && !seen.has(to)) {
          seen.add(to)
          queue.push(to)
        }
      }
    }
    return seen
  }
  const result = new Set([...walk('down'), ...walk('up')])
  for (const node of scene.nodes) {
    if (node.parentId && result.has(node.id)) result.add(node.parentId)
    if (node.parentId === id) result.add(node.id)
  }
  return result
}

interface CanvasProps {
  graph: ArchitectureGraph
  view: ViewMode
  /** Real node id -> what the trace says it is doing. */
  activity: Record<string, NodeActivity>
  stickyErrors: Set<string>
  selectedId: string | null
  onSelect: (sceneNodeId: string) => void
  /** Real node id the camera should move to while follow is on. */
  focusNodeId: string | null
  follow: boolean
  onUserMove: () => void
  onScene?: (scene: Scene) => void
}

function CanvasInner({
  graph,
  view,
  activity,
  stickyErrors,
  selectedId,
  onSelect,
  focusNodeId,
  follow,
  onUserMove,
  onScene,
}: CanvasProps) {
  const reduced = useReducedMotion()
  const flow = useReactFlow()
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const scene = useMemo(() => buildScene(graph, view), [graph, view])
  const onSceneRef = useRef(onScene)
  onSceneRef.current = onScene

  useEffect(() => {
    onSceneRef.current?.(scene)
  }, [scene])

  // Only refit when the picture's shape changes, not on every status poll.
  const shapeKey = `${view}:${scene.width}x${scene.height}:${scene.nodes.length}:${scene.edges.length}`
  const containerRef = useRef<HTMLDivElement>(null)
  /** Detailed is for reading, so it fits the diagram's width and scrolls vertically; the
   * other two views fit the whole picture. */
  const fit = useCallback(() => {
    const duration = reduced ? 0 : 320
    const box = containerRef.current?.getBoundingClientRect()
    if (view === 'detailed' && box && scene.width > 0) {
      const zoom = Math.min(1, (box.width - 32) / scene.width)
      void flow.setViewport({ x: (box.width - scene.width * zoom) / 2, y: 16, zoom }, { duration })
      return
    }
    void flow.fitView({ padding: 0.05, duration })
  }, [flow, reduced, scene.width, view])

  useEffect(() => {
    const frame = requestAnimationFrame(fit)
    return () => cancelAnimationFrame(frame)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refit on a new shape, not on every status poll
  }, [shapeKey])

  useEffect(() => {
    if (!follow || !focusNodeId) return
    const target = scene.nodes.find((n) => n.id === scene.nodeFor[focusNodeId])
    if (!target) return
    const zoom = Math.max(flow.getZoom(), view === 'overview' ? 0.9 : 1)
    void flow.setCenter(target.rect.x + target.rect.width / 2, target.rect.y + target.rect.height / 2, {
      zoom,
      duration: reduced ? 0 : 600,
    })
  }, [follow, focusNodeId, scene, flow, reduced, view])

  const highlighted = useMemo(() => (hoveredId ? connectedInScene(hoveredId, scene) : null), [hoveredId, scene])
  const handleHover = useCallback((id: string | null) => setHoveredId(id), [])

  const sceneActivity = useMemo(() => {
    const result: Record<string, NodeActivity> = {}
    const rank: Record<NodeActivity, number> = { idle: 0, done: 1, blocked: 2, error: 3, active: 4 }
    for (const [realId, state] of Object.entries(activity)) {
      const sceneId = scene.nodeFor[realId]
      if (!sceneId) continue
      if (!result[sceneId] || rank[state] > rank[result[sceneId]]) result[sceneId] = state
    }
    return result
  }, [activity, scene])

  const sceneErrors = useMemo(() => new Set([...stickyErrors].map((id) => scene.nodeFor[id]).filter(Boolean)), [stickyErrors, scene])

  const nodes: Node[] = useMemo(() => {
    const lanes: Node[] = scene.lanes.map((lane) => ({
      id: `lane:${lane.stage ?? 'none'}`,
      type: 'lane',
      position: { x: lane.x, y: lane.y },
      style: { width: lane.width, height: lane.height },
      data: { label: lane.label, stage: lane.stage },
      draggable: false,
      selectable: false,
      focusable: false,
      zIndex: -1,
    }))
    const ordered = [...scene.nodes].sort((a, b) => Number(b.kind === 'cluster') - Number(a.kind === 'cluster'))
    const real: Node[] = ordered.map((n) => {
      const data: CanvasNodeData = {
        order: n.order,
        dimmed: highlighted !== null && !highlighted.has(n.id),
        activity: sceneActivity[n.id] ?? 'idle',
        stickyError: sceneErrors.has(n.id),
        selected: selectedId === n.id,
        showConfig: view === 'detailed',
        node: n.node,
        summary: n.summary,
        childCount: n.childCount,
        onSelect,
        onHover: handleHover,
      }
      return {
        id: n.id,
        type: n.kind,
        position: n.parentId && n.relative ? n.relative : { x: n.rect.x, y: n.rect.y },
        parentId: n.parentId,
        extent: n.parentId ? ('parent' as const) : undefined,
        style: { width: n.rect.width, height: n.rect.height },
        data,
        draggable: false,
        selectable: false,
        focusable: false,
      }
    })
    return [...lanes, ...real]
  }, [scene, highlighted, sceneActivity, sceneErrors, selectedId, view, onSelect, handleHover])

  const edges: Edge[] = useMemo(
    () =>
      scene.edges.map((e) => {
        const onPath = highlighted !== null && highlighted.has(e.source) && highlighted.has(e.target)
        const data: FlowEdgeData = {
          kind: e.kind,
          label: e.label,
          path: e.path,
          sourceOrder: e.sourceOrder,
          far: e.far,
          dimmed: highlighted !== null && !onPath,
          highlighted: onPath,
        }
        return { id: e.id, source: e.source, target: e.target, type: 'flow', data, focusable: false, selectable: false }
      }),
    [scene, highlighted],
  )

  return (
    <div ref={containerRef} className="relative h-full w-full" data-testid="architecture-canvas" data-view={view} data-node-count={scene.nodes.length} data-edge-count={scene.edges.length}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        elementsSelectable={false}
        minZoom={0.2}
        maxZoom={2}
        zoomOnScroll={false}
        zoomOnPinch
        panOnScroll
        zoomActivationKeyCode={['Meta', 'Control']}
        onMoveStart={(event) => {
          if (event) onUserMove()
        }}
        aria-label="System architecture diagram"
      />
      <div className="absolute right-3 bottom-8 flex gap-1 rounded-lg border border-border bg-surface p-1 shadow-sm" role="toolbar" aria-label="Diagram zoom">
        <Button variant="ghost" size="icon-sm" aria-label="Zoom out" onClick={() => void flow.zoomOut({ duration: reduced ? 0 : 200 })}>
          <Minus className="size-3.5" />
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Zoom in" onClick={() => void flow.zoomIn({ duration: reduced ? 0 : 200 })}>
          <Plus className="size-3.5" />
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Fit diagram to view" data-testid="arch-fit" onClick={fit}>
          <Maximize2 className="size-3.5" />
        </Button>
      </div>
    </div>
  )
}

/** The diagram. `key={view}` on the provider remounts it per view so the entrance plays. */
export function ArchitectureCanvas(props: CanvasProps) {
  return (
    <ReactFlowProvider key={props.view}>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  )
}
