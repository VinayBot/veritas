/** Imperative packet animation. A packet is a few SVG circles moved along an edge by the
 * Web Animations API using transform keyframes only — no React state per frame, nothing that
 * triggers layout. The page emits when a real trace hop arrives; the edge is looked up then. */
import type { EdgeKind } from '@/lib/api/types'

export interface PacketRequest {
  durationMs: number
  delayMs: number
  kind: EdgeKind
}

const running = new Set<Animation>()
let drawn = 0

/** Packet colour by kind of hop. */
export const PACKET_COLOR: Record<EdgeKind, string> = {
  request: 'var(--color-accent-soft)',
  data: 'var(--color-live)',
  trace: 'var(--color-success)',
  optional: 'var(--color-warning)',
}

/** How many packets have actually been drawn since the page loaded. */
export function packetsDrawn(): number {
  return drawn
}

const SAMPLES = 24

/**
 * Draws a packet along an edge, if that edge is on screen. Returns whether it was drawn.
 *
 * The edge is found in the document at the moment of the call, and its route is measured
 * off the path that is actually drawn. Nothing is registered ahead of time: a subscription
 * kept by each edge component could be torn down and re-created by a re-render or a remount
 * of the canvas, and a packet for a real event emitted in that gap was silently lost.
 */
export function emitPacket(edgeId: string, packet: PacketRequest): boolean {
  const layer = document.querySelector<SVGGElement>(`[data-packet-layer="${CSS.escape(edgeId)}"]`)
  const path = layer?.parentElement?.querySelector<SVGPathElement>('path[data-edge-path]')
  if (!layer || !path) return false
  const length = path.getTotalLength()
  if (!(length > 0)) return false
  const points = Array.from({ length: SAMPLES + 1 }, (_, i) => {
    const point = path.getPointAtLength((length * i) / SAMPLES)
    return { x: point.x, y: point.y }
  })
  animatePacket(layer, points, packet, PACKET_COLOR[packet.kind])
  return true
}

/** Stops every packet in flight — used the moment the trace socket closes. */
export function cancelAllPackets(): void {
  for (const animation of [...running]) animation.cancel()
  running.clear()
}

export function activePacketCount(): number {
  return running.size
}

const SVG_NS = 'http://www.w3.org/2000/svg'
const TAIL = [
  { radius: 5, opacity: 1, lagMs: 0 },
  { radius: 4, opacity: 0.55, lagMs: 45 },
  { radius: 3, opacity: 0.3, lagMs: 90 },
  { radius: 2.2, opacity: 0.15, lagMs: 135 },
]

export function animatePacket(
  layer: SVGGElement,
  points: { x: number; y: number }[],
  packet: PacketRequest,
  color: string,
): void {
  drawn += 1
  const keyframes = points.map((p) => ({ transform: `translate(${p.x}px, ${p.y}px)` }))
  for (const segment of TAIL) {
    const circle = document.createElementNS(SVG_NS, 'circle')
    circle.setAttribute('r', String(segment.radius))
    circle.style.fill = color
    circle.setAttribute('opacity', '0')
    circle.setAttribute('data-packet', 'true')
    circle.style.willChange = 'transform, opacity'
    layer.appendChild(circle)
    const animation = circle.animate(
      keyframes.map((frame, i) => ({
        ...frame,
        opacity: i === 0 || i === keyframes.length - 1 ? 0 : segment.opacity,
      })),
      { duration: packet.durationMs, delay: packet.delayMs + segment.lagMs, easing: 'linear', fill: 'both' },
    )
    running.add(animation)
    const cleanup = () => {
      running.delete(animation)
      circle.remove()
    }
    animation.onfinish = cleanup
    animation.oncancel = cleanup
  }
}
