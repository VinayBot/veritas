import type { ReactNode } from 'react'
import { CircleHelp } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip'
import { GLOSSARY, type GlossaryTerm } from '@/lib/glossary'
import { cn } from '@/lib/utils'

/** A label with a plain-English explanation on hover or keyboard focus. Pass `term` for a
 * glossary entry or `tip` for one-off text. */
export function MetricTip({
  term,
  tip,
  children,
  className,
}: {
  term?: GlossaryTerm
  tip?: string
  children: ReactNode
  className?: string
}) {
  const text = tip ?? (term ? GLOSSARY[term] : undefined)
  if (!text) return <span className={className}>{children}</span>
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex cursor-help items-center gap-1 rounded-sm text-left underline decoration-dotted decoration-muted-foreground/50 underline-offset-4',
            className,
          )}
        >
          {children}
          <CircleHelp className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" sideOffset={6} className="max-w-xs text-left leading-relaxed">
        {text}
      </TooltipContent>
    </Tooltip>
  )
}
