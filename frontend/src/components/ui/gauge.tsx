import { motion, useMotionValue, useTransform, animate, useReducedMotion } from 'framer-motion'
import { useEffect, useId, useMemo, useRef } from 'react'
import { EASE_ENTER } from '@/lib/motion'
import { EmptyState, type ComponentStatus } from './empty-state'
import { cn } from '@/lib/utils'

interface GaugeProps {
  /** Current value. Only meaningful (and only ever rendered) when status is "success". */
  value: number
  max?: number
  label?: string
  status?: ComponentStatus
  size?: number
  strokeWidth?: number
  formatValue?: (value: number) => string
  emptyDescription?: string
  errorDescription?: string
  className?: string
}

/**
 * Radial gauge: an SVG ring whose stroke sweeps to `value / max`, plus a
 * numeric readout that counts up alongside it. Built from a plain <svg> +
 * Framer Motion rather than a charting library, per the brief.
 */
export function Gauge({
  value,
  max = 100,
  label,
  status = 'success',
  size = 128,
  strokeWidth = 10,
  formatValue,
  emptyDescription,
  errorDescription,
  className,
}: GaugeProps) {
  const reduced = useReducedMotion()
  const gradientId = useId()
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(max, value))
  const fraction = max > 0 ? clamped / max : 0
  // Memoized so its identity only changes when formatValue itself does —
  // the effect below depends on it, and an identity that changed on every
  // render (the default formatter is a fresh closure each time) would
  // restart the sweep animation on every unrelated re-render.
  const format = useMemo(
    () => formatValue ?? ((v: number) => Math.round(v).toString()),
    [formatValue],
  )

  // 0-1 sweep progress, driven imperatively via animate() so the number
  // readout can be written straight to the DOM (see below) instead of
  // forcing a React re-render on every tick. useMotionValue's return is
  // ref-stable for the component's lifetime, same as a ref.
  const progress = useMotionValue(0)
  const dashOffset = useTransform(progress, (p) => circumference * (1 - p))
  const labelRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (status !== 'success') return
    if (labelRef.current) labelRef.current.textContent = format(progress.get() * max)
    const controls = animate(progress, fraction, {
      duration: reduced ? 0 : 1,
      ease: EASE_ENTER,
      onUpdate: (p) => {
        if (labelRef.current) labelRef.current.textContent = format(p * max)
      },
    })
    return () => controls.stop()
  }, [fraction, status, reduced, max, format, progress])

  if (status === 'loading') {
    return (
      <div
        className={cn('flex flex-col items-center gap-3', className)}
        style={{ width: size }}
        aria-label={label ? `Loading ${label}` : 'Loading gauge'}
        role="status"
      >
        <div className="skeleton-shimmer rounded-full" style={{ width: size, height: size }} />
        {label && <span className="text-sm text-muted-foreground">{label}</span>}
      </div>
    )
  }

  if (status === 'empty' || status === 'error') {
    return (
      <div className={cn('flex flex-col items-center gap-2', className)} style={{ width: size }}>
        <div
          className="flex items-center justify-center rounded-full border border-dashed border-border"
          style={{ width: size, height: size }}
        >
          <EmptyState
            tone={status}
            title={status === 'empty' ? 'No data' : 'Error'}
            description={status === 'empty' ? emptyDescription : errorDescription}
            className="gap-1 p-2"
          />
        </div>
        {label && <span className="text-sm text-muted-foreground">{label}</span>}
      </div>
    )
  }

  return (
    <div
      className={cn('inline-flex flex-col items-center gap-2', className)}
      role="meter"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={label ?? 'Gauge'}
    >
      <div className="relative" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          className="-rotate-90"
          aria-hidden="true"
        >
          <defs>
            <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="var(--color-accent-soft)" />
              <stop offset="100%" stopColor="var(--color-accent)" />
            </linearGradient>
          </defs>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--color-border)"
            strokeWidth={strokeWidth}
          />
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={`url(#${gradientId})`}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            style={{ strokeDashoffset: dashOffset }}
          />
        </svg>
        <span
          aria-hidden="true"
          className="absolute inset-0 flex items-center justify-center font-display text-2xl font-semibold tabular-nums text-foreground"
        >
          <span ref={labelRef}>0</span>
        </span>
      </div>
      {label && <span className="text-sm text-muted-foreground">{label}</span>}
    </div>
  )
}
