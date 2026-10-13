/** PNG, SVG and JSON export of the architecture. The picture is rebuilt as a standalone SVG
 * from the same scene the canvas draws (nodes as rectangles, edges as their real paths), so
 * the export is exactly the diagram, with no screenshot library. */
import type { ArchitectureGraph } from '@/lib/api/types'
import type { Scene } from './scene'

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function token(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function escapeXml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

const PAD = 32

export function sceneToSvg(scene: Scene): string {
  const colors = {
    background: token('--color-background', '#07060b'),
    surface: token('--color-surface-raised', '#161522'),
    lane: token('--color-surface', '#0f0e17'),
    border: token('--color-border', '#232233'),
    text: token('--color-foreground', '#f2f1f7'),
    muted: token('--color-muted', '#8d8aa3'),
    accent: token('--color-accent', '#8b5cf6'),
    live: token('--color-live', '#22d3ee'),
    success: token('--color-success', '#34d399'),
    warning: token('--color-warning', '#fbbf24'),
    danger: token('--color-danger', '#f87171'),
  }
  const statusColor: Record<string, string> = {
    healthy: colors.success,
    degraded: colors.warning,
    down: colors.danger,
    disabled: colors.muted,
    not_configured: colors.muted,
  }
  const edgeColor: Record<string, string> = { request: colors.accent, data: colors.muted, trace: colors.live, optional: colors.muted }
  const width = scene.width + PAD * 2
  const height = scene.height + PAD * 2
  const parts: string[] = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="${-PAD} ${-PAD} ${width} ${height}" font-family="Inter, system-ui, sans-serif">`,
    `<rect x="${-PAD}" y="${-PAD}" width="${width}" height="${height}" fill="${colors.background}"/>`,
  ]
  for (const lane of scene.lanes) {
    parts.push(
      `<rect x="${lane.x}" y="${lane.y}" width="${lane.width}" height="${lane.height}" rx="16" fill="${colors.lane}" stroke="${colors.border}" opacity="0.6"/>`,
      `<text x="${lane.x + 16}" y="${lane.y + lane.height / 2}" fill="${colors.muted}" font-size="12">${escapeXml(`${lane.stage ?? ''} ${lane.label}`.trim())}</text>`,
    )
  }
  for (const edge of scene.edges) {
    const dash = edge.kind === 'optional' ? ' stroke-dasharray="6 5"' : edge.kind === 'trace' ? ' stroke-dasharray="2 5"' : ''
    const end = edge.path.points[edge.path.points.length - 1]
    const before = edge.path.points[edge.path.points.length - 2]
    const angle = (Math.atan2(end.y - before.y, end.x - before.x) * 180) / Math.PI
    parts.push(
      `<path d="${edge.path.d}" fill="none" stroke="${edgeColor[edge.kind]}" stroke-width="1.25" opacity="0.75"${dash}/>`,
      `<path d="M0,0 L-7,-3.5 L-7,3.5 Z" fill="${edgeColor[edge.kind]}" transform="translate(${end.x} ${end.y}) rotate(${angle})"/>`,
    )
  }
  for (const node of scene.nodes) {
    const { x, y, width: w, height: h } = node.rect
    if (node.kind === 'cluster') {
      parts.push(
        `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="16" fill="${colors.accent}" fill-opacity="0.05" stroke="${colors.accent}" stroke-opacity="0.4" stroke-dasharray="5 4"/>`,
        `<text x="${x + 16}" y="${y + 25}" fill="${colors.text}" font-size="13" font-weight="600">${escapeXml(node.node?.label ?? node.id)}</text>`,
      )
      continue
    }
    const label = node.node?.label ?? node.summary?.label ?? node.id
    const status = node.node?.status ?? node.summary?.worst ?? 'healthy'
    const sub = node.node?.module_path ?? (node.summary ? `${node.summary.modules.length} modules` : '')
    parts.push(
      `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="${colors.surface}" stroke="${colors.border}"/>`,
      `<circle cx="${x + 16}" cy="${y + 20}" r="4" fill="${statusColor[status] ?? colors.muted}"/>`,
      `<text x="${x + 28}" y="${y + 24}" fill="${colors.text}" font-size="13" font-weight="600">${escapeXml(label)}</text>`,
      `<text x="${x + 16}" y="${y + h - 12}" fill="${colors.muted}" font-size="10" font-family="ui-monospace, monospace">${escapeXml(sub)}</text>`,
    )
  }
  parts.push('</svg>')
  return parts.join('')
}

export function exportArchitectureSvg(scene: Scene, filename = 'veritas-architecture.svg') {
  download(new Blob([sceneToSvg(scene)], { type: 'image/svg+xml' }), filename)
}

export async function exportArchitecturePng(scene: Scene, filename = 'veritas-architecture.png') {
  const markup = sceneToSvg(scene)
  const url = URL.createObjectURL(new Blob([markup], { type: 'image/svg+xml' }))
  try {
    const img = new Image()
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve()
      img.onerror = () => reject(new Error('Could not rasterize the diagram'))
      img.src = url
    })
    const scale = 2
    const canvas = document.createElement('canvas')
    canvas.width = img.width * scale
    canvas.height = img.height * scale
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('2D canvas context unavailable')
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const blob: Blob | null = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!blob) throw new Error('The browser produced no PNG data')
    download(blob, filename)
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** The exact payload the diagram was drawn from. */
export function exportArchitectureJson(graph: ArchitectureGraph, filename = 'veritas-architecture.json') {
  download(new Blob([JSON.stringify(graph, null, 2)], { type: 'application/json' }), filename)
}
