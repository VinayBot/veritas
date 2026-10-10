import type { ReactNode } from 'react'
import { Inbox, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Shared status contract for any component with a meaningful loading/empty/
 * error/success lifecycle (Gauge, Stepper, StatCard, ...). `success` means
 * "render normally with the data given" — it is the default, not a special
 * state — the other three are the ones a component must deliberately render.
 */
export type ComponentStatus = 'loading' | 'empty' | 'error' | 'success'

interface StateMessageProps {
  status: 'empty' | 'error'
  title?: string
  description?: string
  icon?: ReactNode
  className?: string
}

/** The empty/error presentation shared by every status-aware component, so each one doesn't re-invent its own copy and icon. */
export function StateMessage({ status, title, description, icon, className }: StateMessageProps) {
  const isError = status === 'error'

  return (
    <div
      role={isError ? 'alert' : 'status'}
      className={cn(
        'flex flex-col items-center justify-center gap-2 p-6 text-center',
        className,
      )}
    >
      <span className={isError ? 'text-danger' : 'text-muted-foreground'}>
        {icon ?? (isError ? <TriangleAlert className="size-5" /> : <Inbox className="size-5" />)}
      </span>
      <p className="text-sm font-medium text-foreground">
        {title ?? (isError ? 'Something went wrong' : 'No data yet')}
      </p>
      {description && <p className="text-xs text-muted-foreground">{description}</p>}
    </div>
  )
}
