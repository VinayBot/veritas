import type { ReactNode } from 'react'
import { GlowCard } from './glow-card'
import { Skeleton } from './skeleton'
import { StateMessage, type ComponentStatus } from './state-message'
import { cn } from '@/lib/utils'

interface StatCardProps {
  label: string
  value?: ReactNode
  delta?: string
  icon?: ReactNode
  status?: ComponentStatus
  emptyDescription?: string
  errorDescription?: string
  className?: string
}

/**
 * "Card used as a data display" from the brief: a GlowCard composed with a
 * label/value/delta layout and the shared loading/empty/error/success
 * contract. The value is tabular-nums since it's always a number/metric.
 */
export function StatCard({
  label,
  value,
  delta,
  icon,
  status = 'success',
  emptyDescription,
  errorDescription,
  className,
}: StatCardProps) {
  return (
    <GlowCard className={className} contentClassName="min-h-[9rem]">
      {status === 'loading' && (
        <div className="flex h-full flex-col gap-3" aria-label={`Loading ${label}`} role="status">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-3 w-28" />
        </div>
      )}

      {(status === 'empty' || status === 'error') && (
        <StateMessage
          status={status}
          description={status === 'empty' ? emptyDescription : errorDescription}
          className="h-full justify-center"
        />
      )}

      {status === 'success' && (
        <div className="flex h-full flex-col justify-between gap-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium text-muted-foreground">{label}</span>
            {icon && (
              <span aria-hidden="true" className="text-accent-soft">
                {icon}
              </span>
            )}
          </div>
          <span
            className={cn(
              'font-display text-3xl font-semibold tabular-nums text-foreground',
            )}
          >
            {value}
          </span>
          {delta && <span className="text-xs font-medium tabular-nums text-success">{delta}</span>}
        </div>
      )}
    </GlowCard>
  )
}
