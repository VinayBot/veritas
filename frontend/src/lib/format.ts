/** Formatting helpers shared by every page, so the same value never renders two ways. */

export function pct(n: number | null | undefined, digits = 1): string | undefined {
  if (n === null || n === undefined || Number.isNaN(n)) return undefined
  return `${(n * 100).toFixed(digits)}%`
}

export function score(n: number | null | undefined, digits = 2): string | undefined {
  if (n === null || n === undefined || Number.isNaN(n)) return undefined
  return n.toFixed(digits)
}

export function ms(n: number | null | undefined): string | undefined {
  if (n === null || n === undefined || Number.isNaN(n)) return undefined
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}s`
  if (n >= 1000) return `${(n / 1000).toFixed(2)}s`
  return `${Math.round(n)}ms`
}

export function compact(n: number | null | undefined): string | undefined {
  if (n === null || n === undefined || Number.isNaN(n)) return undefined
  return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}

export function bytes(n: number | null | undefined): string | undefined {
  if (n === null || n === undefined || Number.isNaN(n)) return undefined
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = n
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

/** The backend stores naive UTC timestamps; treat a value without a zone as UTC. */
export function parseTime(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
}

export function dateTime(iso: string | null | undefined): string | undefined {
  if (!iso) return undefined
  return parseTime(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function relativeTime(iso: string | number | null | undefined): string | undefined {
  if (iso === null || iso === undefined) return undefined
  const then = typeof iso === 'number' ? iso : parseTime(iso).getTime()
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86_400)}d ago`
}

/** "ollama/llama3.2:3b" -> "llama3.2:3b" */
export function modelName(id: string | null | undefined): string {
  if (!id) return '—'
  return id.replace(/^ollama\//, '')
}
