/** PNG/SVG export for the System Design canvas (AR-7). The canvas already IS an SVG, so
 * exporting it is pure serialization + (for PNG) a canvas rasterization pass — both native
 * browser APIs, no new dependency (G5). */

function cloneWithInlineStyles(svg: SVGSVGElement): SVGSVGElement {
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  const computed = getComputedStyle(svg)
  clone.style.background = computed.backgroundColor || '#000000'
  return clone
}

function serialize(svg: SVGSVGElement): string {
  const clone = cloneWithInlineStyles(svg)
  return new XMLSerializer().serializeToString(clone)
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function exportArchitectureSvg(svg: SVGSVGElement, filename = 'architecture.svg') {
  const markup = serialize(svg)
  download(new Blob([markup], { type: 'image/svg+xml' }), filename)
}

export async function exportArchitecturePng(svg: SVGSVGElement, filename = 'architecture.png') {
  const markup = serialize(svg)
  const svgBlob = new Blob([markup], { type: 'image/svg+xml' })
  const url = URL.createObjectURL(svgBlob)
  try {
    const img = new Image()
    const loaded = new Promise<void>((resolve, reject) => {
      img.onload = () => resolve()
      img.onerror = () => reject(new Error('Failed to rasterize architecture SVG'))
    })
    img.src = url
    await loaded

    const scale = 2 // crisp export on standard displays
    const viewBox = svg.viewBox.baseVal
    const width = (viewBox?.width || svg.clientWidth) * scale
    const height = (viewBox?.height || svg.clientHeight) * scale

    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('2D canvas context unavailable')
    ctx.fillStyle = '#000000'
    ctx.fillRect(0, 0, width, height)
    ctx.drawImage(img, 0, 0, width, height)

    const pngBlob: Blob | null = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!pngBlob) throw new Error('Canvas failed to produce a PNG blob')
    download(pngBlob, filename)
  } finally {
    URL.revokeObjectURL(url)
  }
}
