import type { ReactNode } from 'react'
import { Inbox, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { explainError } from '@/lib/errors'

/**
 * Shared status contract for any component with a loading/empty/error/success lifecycle.
 * `success` means "render normally with the data given"; the other three are the ones a
 * component must deliberately render.
 */
export type ComponentStatus = 'loading' | 'empty' | 'error' | 'success'

interface EmptyStateProps {
  tone?: 'empty' | 'error'
  title?: string
  description?: ReactNode
  icon?: ReactNode
  /** A real next step (button or link) — an empty state is a call to action, not a dead end. */
  action?: ReactNode
  compact?: boolean
  className?: string
}

/** The one empty/error placeholder every page and panel uses. Never shows a fake value. */
export function EmptyState({
  tone = 'empty',
  title,
  description,
  icon,
  action,
  compact,
  className,
}: EmptyStateProps) {
  const isError = tone === 'error'
  return (
    <div
      role={isError ? 'alert' : 'status'}
      className={cn(
        'flex flex-col items-center justify-center gap-2 text-center',
        compact ? 'p-3' : 'p-6',
        className,
      )}
    >
      <span className={isError ? 'text-danger' : 'text-muted-foreground'} aria-hidden="true">
        {icon ?? (isError ? <TriangleAlert className="size-5" /> : <Inbox className="size-5" />)}
      </span>
      <p className="text-sm font-medium text-foreground">
        {title ?? (isError ? 'Something went wrong' : 'No data yet')}
      </p>
      {description && <p className="max-w-sm text-xs text-muted-foreground">{description}</p>}
      {action && <div className="mt-1 flex items-center gap-2">{action}</div>}
    </div>
  )
}

/** An error with the real message, a plain-English explanation and a suggested fix. */
export function ErrorState({
  error,
  action,
  compact,
  className,
}: {
  error: unknown
  action?: ReactNode
  compact?: boolean
  className?: string
}) {
  const info = explainError(error)
  return (
    <EmptyState
      tone="error"
      title={info.title}
      compact={compact}
      className={className}
      action={action}
      description={
        <>
          <span className="block">{info.explanation}</span>
          {info.fix && <span className="mt-1 block text-foreground">{info.fix}</span>}
          <code className="mt-2 block rounded-md bg-surface-raised px-2 py-1 text-left font-mono text-[11px] break-words whitespace-pre-wrap text-muted-foreground">
            {info.raw}
          </code>
        </>
      }
    />
  )
}
