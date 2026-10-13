import type { ReactNode } from 'react'
import { ArrowDownRight, ArrowUpRight } from 'lucide-react'
import { Skeleton } from './skeleton'
import { Sparkline } from './sparkline'
import { MetricTip } from './metric-tip'
import type { GlossaryTerm } from '@/lib/glossary'
import { cn } from '@/lib/utils'

export interface StatDelta {
  /** Whether the change is an improvement, independent of its sign (lower latency is good). */
  good: boolean
  direction: 'up' | 'down'
  label: string
}

interface StatCardProps {
  label: string
  term?: GlossaryTerm
  tip?: string
  /** Undefined means "not measured" — the card says so instead of showing a number. */
  value?: ReactNode
  delta?: StatDelta
  trend?: number[]
  caption?: ReactNode
  icon?: ReactNode
  loading?: boolean
  emptyLabel?: string
  className?: string
  testId?: string
}

/** The one KPI card: label with an explanation, value, optional delta, sparkline and caption. */
export function StatCard({
  label,
  term,
  tip,
  value,
  delta,
  trend,
  caption,
  icon,
  loading,
  emptyLabel = 'Not measured',
  className,
  testId,
}: StatCardProps) {
  return (
    <div
      data-testid={testId}
      className={cn(
        'rise-in flex min-h-32 flex-col justify-between gap-3 rounded-xl border border-border bg-surface p-4 shadow-xs',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <MetricTip term={term} tip={tip} className="text-xs font-medium text-muted-foreground">
          {label}
        </MetricTip>
        {icon && (
          <span aria-hidden="true" className="text-accent-soft">
            {icon}
          </span>
        )}
      </div>
      {loading ? (
        <div className="flex flex-col gap-2" role="status" aria-label={`Loading ${label}`}>
          <Skeleton className="h-8 w-20" />
          <Skeleton className="h-3 w-28" />
        </div>
      ) : (
        <>
          <div className="flex items-end justify-between gap-2">
            {value === undefined || value === null ? (
              <span className="text-sm font-medium text-muted-foreground">{emptyLabel}</span>
            ) : (
              <span className="font-display text-3xl leading-none font-semibold tabular-nums text-foreground">
                {value}
              </span>
            )}
            {trend && <Sparkline values={trend} label={`${label} trend`} />}
          </div>
          <div className="flex min-h-4 flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            {delta && (
              <span
                className={cn(
                  'inline-flex items-center gap-0.5 font-medium tabular-nums',
                  delta.good ? 'text-success' : 'text-danger',
                )}
              >
                {delta.direction === 'up' ? (
                  <ArrowUpRight className="size-3" aria-hidden="true" />
                ) : (
                  <ArrowDownRight className="size-3" aria-hidden="true" />
                )}
                {delta.label}
              </span>
            )}
            {caption && <span className="text-muted-foreground">{caption}</span>}
          </div>
        </>
      )}
    </div>
  )
}
