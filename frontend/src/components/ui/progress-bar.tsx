import { cn } from '@/lib/utils'

/** Determinate progress. `value` is 0..1 from a real backend event; undefined shows an
 * indeterminate track with no made-up percentage. Animates transform only. */
export function ProgressBar({
  value,
  label,
  tone = 'accent',
  className,
}: {
  value?: number
  label: string
  tone?: 'accent' | 'live' | 'success' | 'warning' | 'danger'
  className?: string
}) {
  const clamped = value === undefined ? undefined : Math.max(0, Math.min(1, value))
  const fill = {
    accent: 'bg-accent',
    live: 'bg-live',
    success: 'bg-success',
    warning: 'bg-warning',
    danger: 'bg-danger',
  }[tone]
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped === undefined ? undefined : Math.round(clamped * 100)}
      className={cn('h-1.5 w-full overflow-hidden rounded-pill bg-surface-raised', className)}
    >
      <div
        className={cn('h-full w-full origin-left rounded-pill transition-transform duration-standard ease-enter', fill, clamped === undefined ? 'opacity-40' : clamped < 1 && 'progress-live')}
        style={{ transform: `scaleX(${clamped ?? 1})` }}
      />
    </div>
  )
}

/** An inline bar for a 0..1 metric inside a table cell. */
export function InlineBar({ value, className }: { value: number; className?: string }) {
  const clamped = Math.max(0, Math.min(1, value))
  return (
    <span className={cn('inline-flex w-full items-center gap-2', className)}>
      <span className="h-1.5 flex-1 overflow-hidden rounded-pill bg-surface-raised" aria-hidden="true">
        <span className="block h-full origin-left rounded-pill bg-accent" style={{ transform: `scaleX(${clamped})` }} />
      </span>
      <span className="w-10 text-right tabular-nums">{(clamped * 100).toFixed(0)}%</span>
    </span>
  )
}
