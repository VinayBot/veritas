import { useMemo, useState, type ReactNode } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { MetricTip } from './metric-tip'
import type { GlossaryTerm } from '@/lib/glossary'
import { DURATION, EASE_ENTER, staggerDelay } from '@/lib/motion'
import { cn } from '@/lib/utils'

export interface Column<T> {
  key: string
  header: string
  term?: GlossaryTerm
  tip?: string
  align?: 'left' | 'right'
  /** Returning undefined sorts the row last, whichever direction is active. */
  sortValue?: (row: T) => number | string | undefined | null
  render: (row: T) => ReactNode
  className?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  /** Read by screen readers; describes what the table holds. */
  caption: string
  initialSort?: { key: string; direction: 'asc' | 'desc' }
  onRowClick?: (row: T) => void
  empty?: ReactNode
  className?: string
  testId?: string
}

/** The one table: sortable headers with aria-sort, keyboard-activatable rows, staggered entrance. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  initialSort,
  onRowClick,
  empty,
  className,
  testId,
}: DataTableProps<T>) {
  const [sort, setSort] = useState(initialSort ?? null)
  const reduced = useReducedMotion()

  const sorted = useMemo(() => {
    if (!sort) return rows
    const column = columns.find((c) => c.key === sort.key)
    if (!column?.sortValue) return rows
    const sign = sort.direction === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = column.sortValue!(a)
      const bv = column.sortValue!(b)
      if (av === undefined || av === null) return 1
      if (bv === undefined || bv === null) return -1
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sign
      return String(av).localeCompare(String(bv)) * sign
    })
  }, [rows, sort, columns])

  if (rows.length === 0 && empty) return <>{empty}</>

  function toggle(key: string) {
    setSort((prev) =>
      prev?.key === key
        ? { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' }
        : { key, direction: 'desc' },
    )
  }

  return (
    <div className={cn('overflow-x-auto', className)} data-testid={testId}>
      <table className="w-full border-collapse text-left text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            {columns.map((c) => {
              const active = sort?.key === c.key
              const ariaSort = !c.sortValue ? undefined : active ? (sort!.direction === 'asc' ? 'ascending' : 'descending') : 'none'
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={ariaSort}
                  className={cn('py-2 pr-4 font-medium whitespace-nowrap', c.align === 'right' && 'text-right', c.className)}
                >
                  <span className={cn('inline-flex items-center gap-1', c.align === 'right' && 'flex-row-reverse')}>
                    <MetricTip term={c.term} tip={c.tip}>
                      {c.header}
                    </MetricTip>
                    {c.sortValue && (
                      <button
                        type="button"
                        onClick={() => toggle(c.key)}
                        aria-label={`Sort by ${c.header}`}
                        className="rounded-sm p-0.5 text-muted-foreground transition-colors duration-micro hover:text-foreground"
                      >
                        {active ? (
                          sort!.direction === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />
                        ) : (
                          <ChevronsUpDown className="size-3" />
                        )}
                      </button>
                    )}
                  </span>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <motion.tr
              key={rowKey(row)}
              initial={reduced ? false : { opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: reduced ? 0 : DURATION.standard, ease: EASE_ENTER, delay: reduced ? 0 : staggerDelay(i) }}
              tabIndex={onRowClick ? 0 : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={
                onRowClick
                  ? (e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onRowClick(row)
                      }
                    }
                  : undefined
              }
              className={cn(
                'border-b border-border/60 text-foreground last:border-0',
                onRowClick && 'cursor-pointer transition-colors duration-micro hover:bg-surface-raised',
              )}
            >
              {columns.map((c) => (
                <td key={c.key} className={cn('py-2.5 pr-4 align-middle tabular-nums', c.align === 'right' && 'text-right', c.className)}>
                  {c.render(row)}
                </td>
              ))}
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
