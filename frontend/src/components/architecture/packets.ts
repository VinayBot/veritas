/** Imperative packet animation. A packet is a few SVG circles moved along an edge by the
 * Web Animations API using transform keyframes only — no React state per frame, nothing that
 * triggers layout. Edges subscribe by id; the page emits when a real trace hop arrives. */
import type { EdgeKind } from '@/lib/api/types'

export interface PacketRequest {
  durationMs: number
  delayMs: number
  kind: EdgeKind
}

type Listener = (packet: PacketRequest) => void

const listeners = new Map<string, Set<Listener>>()
const running = new Set<Animation>()
let drawn = 0

/** How many packets have actually been drawn since the page loaded. */
export function packetsDrawn(): number {
  return drawn
}

export function onPacket(edgeId: string, listener: Listener): () => void {
  const set = listeners.get(edgeId) ?? new Set()
  set.add(listener)
  listeners.set(edgeId, set)
  return () => {
    set.delete(listener)
    if (set.size === 0) listeners.delete(edgeId)
  }
}

export function emitPacket(edgeId: string, packet: PacketRequest): void {
  listeners.get(edgeId)?.forEach((listener) => listener(packet))
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
