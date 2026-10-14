import { cn } from '@/lib/utils'
import { STATUS_LABEL, type HealthStatus } from './status-label'

const DOT: Record<HealthStatus, string> = {
  healthy: 'bg-success',
  degraded: 'bg-warning',
  down: 'bg-danger',
  disabled: 'bg-muted',
  not_configured: 'border border-dashed border-muted bg-transparent',
  unknown: 'bg-muted/50',
}

/** Status as colour plus shape, so "disabled" and "not configured" never read as "broken". */
export function StatusDot({ status, className }: { status: HealthStatus; className?: string }) {
  return (
    <span
      className={cn('inline-block size-2 shrink-0 rounded-full', DOT[status], status === 'healthy' && 'dot-live', className)}
      role="img"
      aria-label={STATUS_LABEL[status]}
    />
  )
}
