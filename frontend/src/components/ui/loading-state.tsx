import { Skeleton } from './skeleton'
import { cn } from '@/lib/utils'

type Shape = 'cards' | 'table' | 'chart' | 'lines' | 'graph'

/** Skeletons shaped like the content they stand in for. Full panels never show a spinner. */
export function LoadingState({
  shape = 'lines',
  rows = 4,
  label = 'Loading',
  className,
}: {
  shape?: Shape
  rows?: number
  label?: string
  className?: string
}) {
  return (
    <div role="status" aria-label={label} className={cn('w-full', className)}>
      {shape === 'cards' && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-8 w-20" />
              <Skeleton className="h-3 w-32" />
            </div>
          ))}
        </div>
      )}
      {shape === 'table' && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-8 w-full" />
          {Array.from({ length: rows }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      )}
      {shape === 'chart' && (
        <div className="flex h-64 items-end gap-2">
          {[40, 65, 50, 80, 60, 90, 70, 55, 75, 85].map((h, i) => (
            <Skeleton key={i} className="flex-1" style={{ height: `${h}%` }} />
          ))}
        </div>
      )}
      {shape === 'lines' && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: rows }).map((_, i) => (
            <Skeleton key={i} className={cn('h-3', i % 3 === 2 ? 'w-2/3' : 'w-full')} />
          ))}
        </div>
      )}
      {shape === 'graph' && (
        <div className="grid h-full min-h-64 grid-cols-5 items-center gap-6 p-6">
          {Array.from({ length: 5 }).map((_, col) => (
            <div key={col} className="flex flex-col gap-4">
              {Array.from({ length: col % 2 === 0 ? 3 : 2 }).map((__, i) => (
                <Skeleton key={i} className="h-14 w-full rounded-xl" />
              ))}
            </div>
          ))}
        </div>
      )}
      <span className="sr-only">{label}</span>
    </div>
  )
}
