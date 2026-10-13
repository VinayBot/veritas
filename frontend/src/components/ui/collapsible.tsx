import { useId, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { MetricTip } from './metric-tip'
import type { GlossaryTerm } from '@/lib/glossary'
import { cn } from '@/lib/utils'

function readStored(key: string, fallback: boolean): boolean {
  try {
    const raw = window.localStorage.getItem(`veritas:section:${key}`)
    return raw === null ? fallback : raw === '1'
  } catch {
    return fallback
  }
}

/** A section that opens and closes, remembering which across visits. The header is a real
 * button, so it works from the keyboard. */
export function Collapsible({
  id,
  title,
  term,
  tip,
  summary,
  defaultOpen = true,
  children,
  className,
}: {
  /** Stable key for remembering the open/closed state. */
  id: string
  title: string
  term?: GlossaryTerm
  tip?: string
  /** Shown on the header's right, so a closed section still says something. */
  summary?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
  className?: string
}) {
  const [open, setOpen] = useState(() => readStored(id, defaultOpen))
  const panelId = useId()

  function toggle() {
    setOpen((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem(`veritas:section:${id}`, next ? '1' : '0')
      } catch {
        // Not being able to remember the preference is harmless.
      }
      return next
    })
  }

  return (
    <section className={cn('rounded-xl border border-border bg-surface-raised', className)} data-testid={`section-${id}`} data-open={open}>
      <div className="flex items-center gap-2 px-3 py-2.5">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls={panelId}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md text-left"
        >
          <ChevronDown className={cn('size-3.5 shrink-0 text-muted-foreground transition-transform duration-standard ease-enter', !open && '-rotate-90')} aria-hidden="true" />
          <span className="font-display text-sm font-semibold text-foreground">{title}</span>
        </button>
        {(term || tip) && (
          <MetricTip term={term} tip={tip} className="text-[11px] text-muted-foreground">
            what is this
          </MetricTip>
        )}
        {summary && <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{summary}</span>}
      </div>
      {open && (
        <div id={panelId} className="border-t border-border px-3 py-3">
          {children}
        </div>
      )}
    </section>
  )
}
