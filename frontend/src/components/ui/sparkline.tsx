import { cn } from '@/lib/utils'

/** A tiny trend line over real values. Renders nothing for fewer than two points. */
export function Sparkline({
  values,
  width = 96,
  height = 28,
  className,
  label,
}: {
  values: number[]
  width?: number
  height?: number
  className?: string
  label?: string
}) {
  if (values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = width / (values.length - 1)
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
    .join(' ')
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn('text-accent-soft', className)}
      role="img"
      aria-label={label ?? `Trend over ${values.length} runs`}
    >
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
