import { cn } from '@/lib/utils'

export type HealthStatus = 'healthy' | 'degraded' | 'down' | 'disabled' | 'not_configured' | 'unknown'

const DOT: Record<HealthStatus, string> = {
  healthy: 'bg-success',
  degraded: 'bg-warning',
  down: 'bg-danger',
  disabled: 'bg-muted',
  not_configured: 'border border-dashed border-muted bg-transparent',
  unknown: 'bg-muted/50',
}

export const STATUS_LABEL: Record<HealthStatus, string> = {
  healthy: 'healthy',
  degraded: 'degraded',
  down: 'down',
  disabled: 'disabled',
  not_configured: 'not configured',
  unknown: 'not checked',
}

/** Status as colour plus shape, so "disabled" and "not configured" never read as "broken". */
export function StatusDot({ status, className }: { status: HealthStatus; className?: string }) {
  return (
    <span
      className={cn('inline-block size-2 shrink-0 rounded-full', DOT[status], className)}
      role="img"
      aria-label={STATUS_LABEL[status]}
    />
  )
}
