import type { ReactNode } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { MetricTip } from './metric-tip'
import type { GlossaryTerm } from '@/lib/glossary'
import { DURATION, EASE_ENTER } from '@/lib/motion'
import { cn } from '@/lib/utils'

/** Page wrapper: cross-fade plus an 8px upward slide on mount, no layout shift. */
export function Page({ children, className, testId }: { children: ReactNode; className?: string; testId?: string }) {
  const reduced = useReducedMotion()
  return (
    <motion.div
      data-testid={testId}
      initial={reduced ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduced ? 0 : DURATION.large, ease: EASE_ENTER }}
      className={cn('mx-auto flex w-full max-w-[1600px] flex-col gap-6 p-6', className)}
    >
      {children}
    </motion.div>
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="blade-edge font-display text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
        {description && <p className="mt-3 max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

/** A titled panel. Every page section is one of these. */
export function Panel({
  title,
  term,
  tip,
  description,
  actions,
  children,
  className,
  bodyClassName,
  testId,
  id,
}: {
  title?: string
  term?: GlossaryTerm
  tip?: string
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  testId?: string
  id?: string
}) {
  return (
    <section
      id={id}
      data-testid={testId}
      className={cn('rise-in flex flex-col gap-4 rounded-xl border border-border bg-surface p-5 shadow-xs', className)}
    >
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title && (
              <h2 className="font-display text-sm font-semibold text-foreground">
                <MetricTip term={term} tip={tip}>
                  {title}
                </MetricTip>
              </h2>
            )}
            {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cn('min-w-0', bodyClassName)}>{children}</div>
    </section>
  )
}
