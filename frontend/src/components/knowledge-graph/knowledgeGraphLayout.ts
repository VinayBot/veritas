import { SimplexNoise } from './simplexNoise'
import type { GraphEdge, GraphNode } from '@/lib/api/types'

export const TORUS_SEED = 1337
export const MAJOR_RADIUS = 1.0
export const MINOR_RADIUS = 0.45
export const NOISE_AMPLITUDE = 0.12
export const NOISE_FREQUENCY = 0.9

const noise = new SimplexNoise(TORUS_SEED)

/** KG-2: parametric torus (u = major angle, v = minor angle) displaced along its own normal
 * by low-frequency simplex noise, with an asymmetric major radius so the hole sits off-centre
 * rather than perfectly concentric — both deterministic given (u, v), so the shape is stable
 * across reloads (G1-adjacent: the lumpy silhouette is math, not randomness re-rolled per
 * visit). */
export function torusSurfacePoint(u: number, v: number): [number, number, number] {
  const rEff = MAJOR_RADIUS + 0.12 * Math.cos(u + 1.3)
  const cosV = Math.cos(v)
  const sinV = Math.sin(v)
  const cosU = Math.cos(u)
  const sinU = Math.sin(u)

  let x = (rEff + MINOR_RADIUS * cosV) * cosU
  let y = (rEff + MINOR_RADIUS * cosV) * sinU
  let z = MINOR_RADIUS * sinV

  const nx = cosV * cosU
  const ny = cosV * sinU
  const nz = sinV
  const n = noise.noise3D(cosU * NOISE_FREQUENCY, sinU * NOISE_FREQUENCY, v * NOISE_FREQUENCY)
  x += nx * n * NOISE_AMPLITUDE
  y += ny * n * NOISE_AMPLITUDE
  z += nz * n * NOISE_AMPLITUDE

  return [x, y, z]
}

// Upper-left cool white-blue -> lower-right mauve/pink (KG-1's reference gradient).
const COLOR_A: [number, number, number] = [0xcf / 255, 0xd3 / 255, 0xff / 255]
const COLOR_B: [number, number, number] = [0xc7 / 255, 0x9b / 255, 0xd0 / 255]

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

/** Gradient position: a diagonal (upper-left -> lower-right) parameter in [0,1], plus a small
 * per-community shift so communities read as distinct without becoming a rainbow (KG-3). */
export function gradientColor(u: number, v: number, communityIndex: number, communityCount: number): [number, number, number] {
  const [x, , z] = torusSurfacePoint(u, v)
  let t = (x - z) / (2 * (MAJOR_RADIUS + MINOR_RADIUS))
  t = Math.min(1, Math.max(0, t * 0.5 + 0.5))
  const shift = communityCount > 1 ? (communityIndex / communityCount) * 0.3 - 0.15 : 0
  t = Math.min(1, Math.max(0, t + shift))
  return [lerp(COLOR_A[0], COLOR_B[0], t), lerp(COLOR_A[1], COLOR_B[1], t), lerp(COLOR_A[2], COLOR_B[2], t)]
}

export interface FieldPoint {
  position: [number, number, number]
}

/** KG-3(a): the dim decorative lattice forming the surface — evenly spaced in (u, v)
 * parameter space, which is exactly why points bunch up visually near the silhouette (the
 * brief's own description) once projected. */
export function buildFieldPoints(count: number): FieldPoint[] {
  const points: FieldPoint[] = []
  // A near-golden-angle (u, v) lattice gives even parameter-space coverage without a visible
  // grid, standard for point-on-torus sampling.
  const goldenAngle = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < count; i++) {
    const u = (i * goldenAngle) % (Math.PI * 2)
    const v = ((i * goldenAngle * 2.17) % (Math.PI * 2)) - Math.PI
    points.push({ position: torusSurfacePoint(u, v) })
  }
  return points
}

export interface EntityPoint {
  id: string
  name: string
  label: string
  community: number
  degree: number
  position: [number, number, number]
  color: [number, number, number]
  size: number
}

/** KG-3(b): every real entity placed by community (major-circle arc, length ~ sqrt(size)) and
 * degree (minor-circle angle — high degree toward the visible outer rim, low toward the
 * back/inner side); size ~ log(degree+1); color from the shared gradient, shifted per
 * community. Degree and community-membership are derived client-side (counting `edges`,
 * grouping by the real `community` field) since neither is exposed pre-aggregated by the
 * backend (confirmed: GraphNodeOut has no degree field, and no community-count endpoint
 * exists) — this is real data, just assembled here instead of server-side. */
export function buildEntityPoints(nodes: GraphNode[], edges: GraphEdge[]): EntityPoint[] {
  const degreeById = new Map<string, number>()
  for (const edge of edges) {
    degreeById.set(edge.source, (degreeById.get(edge.source) ?? 0) + 1)
    degreeById.set(edge.target, (degreeById.get(edge.target) ?? 0) + 1)
  }

  const byCommunity = new Map<number, GraphNode[]>()
  const noCommunity: GraphNode[] = []
  for (const node of nodes) {
    if (node.community === null || node.community === undefined) {
      noCommunity.push(node)
      continue
    }
    const list = byCommunity.get(node.community) ?? []
    list.push(node)
    byCommunity.set(node.community, list)
  }

  const communityIds = [...byCommunity.keys()].sort((a, b) => a - b)
  const communityCount = communityIds.length + (noCommunity.length > 0 ? 1 : 0)
  const totalWeight = communityIds.reduce((sum, id) => sum + Math.sqrt(byCommunity.get(id)!.length), 0) +
    (noCommunity.length > 0 ? Math.sqrt(noCommunity.length) : 0)

  const result: EntityPoint[] = []
  let cursor = 0
  const maxDegree = Math.max(1, ...nodes.map((n) => degreeById.get(n.id) ?? 0))

  function placeGroup(group: GraphNode[], communityIndex: number, communityLabel: number) {
    const weight = Math.sqrt(group.length)
    const arcLength = totalWeight > 0 ? (weight / totalWeight) * Math.PI * 2 : 0
    const uStart = cursor
    cursor += arcLength
    group.forEach((node, i) => {
      const degree = degreeById.get(node.id) ?? 0
      const u = uStart + (arcLength * (i + 0.5)) / group.length
      // High degree -> v near 0 (outer rim); low/zero degree -> v near PI (toward the back).
      const normalizedDegree = degree / maxDegree
      const v = Math.PI * (1 - normalizedDegree) * (i % 2 === 0 ? 1 : -1)
      const size = 0.02 + Math.log(degree + 1) * 0.012
      const color = gradientColor(u, v, communityIndex, Math.max(1, communityCount))
      result.push({
        id: node.id,
        name: node.name,
        label: node.label,
        community: communityLabel,
        degree,
        position: torusSurfacePoint(u, v),
        color,
        size,
      })
    })
  }

  communityIds.forEach((id, idx) => placeGroup(byCommunity.get(id)!, idx, id))
  if (noCommunity.length > 0) placeGroup(noCommunity, communityIds.length, -1)

  return result
}
