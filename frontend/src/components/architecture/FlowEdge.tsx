import { memo, useEffect, useRef } from 'react'
import type { EdgeProps } from '@xyflow/react'
import { motion, useReducedMotion } from 'framer-motion'
import type { EdgeKind } from '@/lib/api/types'
import { cn } from '@/lib/utils'
import type { EdgePath } from './layout'
import { animatePacket, onPacket } from './packets'

export interface FlowEdgeData extends Record<string, unknown> {
  kind: EdgeKind
  label: string
  path: EdgePath
  sourceOrder: number
  far: boolean
  dimmed: boolean
  highlighted: boolean
}

const STROKE: Record<EdgeKind, string> = {
  request: 'text-accent/70',
  data: 'text-muted-foreground/70',
  trace: 'text-live/70',
  optional: 'text-muted-foreground/45',
}

const DASH: Record<EdgeKind, string | undefined> = {
  request: undefined,
  data: undefined,
  trace: '2 5',
  optional: '6 5',
}

/** Packet colour by kind of hop. */
export const PACKET_COLOR: Record<EdgeKind, string> = {
  request: 'var(--color-accent-soft)',
  data: 'var(--color-live)',
  trace: 'var(--color-success)',
  optional: 'var(--color-warning)',
}

const ENTRANCE_STEP_S = 0.05

export const FlowEdge = memo(function FlowEdge({ id, data }: EdgeProps) {
  const d = data as FlowEdgeData
  const layerRef = useRef<SVGGElement>(null)
  const reduced = useReducedMotion()
  const { points } = d.path

  // Always listening: whether a packet may be drawn at all (socket open, motion allowed) is
  // decided by whoever emits it, in one place.
  useEffect(
    () =>
      onPacket(id, (packet) => {
        if (layerRef.current) animatePacket(layerRef.current, points, packet, PACKET_COLOR[packet.kind])
      }),
    [id, points],
  )

  const end = points[points.length - 1]
  const before = points[points.length - 2]
  const angle = (Math.atan2(end.y - before.y, end.x - before.x) * 180) / Math.PI
  const dash = DASH[d.kind]

  return (
    <g
      data-testid={`arch-edge-${id}`}
      data-kind={d.kind}
      className={cn('transition-opacity duration-[150ms] ease-out', STROKE[d.kind], d.dimmed ? 'opacity-15' : d.far && !d.highlighted ? 'opacity-40' : 'opacity-100')}
    >
      {dash ? (
        // A dashed line cannot be "drawn" by stroke-dashoffset, so it fades in instead.
        <motion.path
          d={d.path.d}
          fill="none"
          stroke="currentColor"
          strokeWidth={d.highlighted ? 2 : 1.25}
          strokeDasharray={dash}
          initial={reduced ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: reduced ? 0 : 0.32, delay: reduced ? 0 : d.sourceOrder * ENTRANCE_STEP_S + 0.3 }}
        />
      ) : (
        <motion.path
          d={d.path.d}
          fill="none"
          stroke="currentColor"
          strokeWidth={d.highlighted ? 2 : 1.25}
          initial={reduced ? false : { pathLength: 0, opacity: 0 }}
          animate={{ pathLength: 1, opacity: 1 }}
          transition={{ duration: reduced ? 0 : 0.32, delay: reduced ? 0 : d.sourceOrder * ENTRANCE_STEP_S + 0.3 }}
        />
      )}
      {!dash && !reduced && !d.dimmed && (
        <path d={d.path.d} fill="none" stroke={PACKET_COLOR[d.kind]} strokeWidth={1.5} strokeLinecap="round" className="edge-flow" aria-hidden="true" data-flow="true" />
      )}
      <path d="M0,0 L-7,-3.5 L-7,3.5 Z" fill="currentColor" transform={`translate(${end.x} ${end.y}) rotate(${angle})`} />
      {d.highlighted && d.label && (
        <text
          x={d.path.labelAt.x}
          y={d.path.labelAt.y - 6}
          textAnchor="middle"
          className="fill-foreground text-[10px] font-medium"
          style={{ paintOrder: 'stroke', stroke: 'var(--color-background)', strokeWidth: 4 }}
        >
          {d.label}
        </text>
      )}
      <g ref={layerRef} data-packet-layer={id} />
    </g>
  )
})
