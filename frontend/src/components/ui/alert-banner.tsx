import { motion, useReducedMotion } from 'framer-motion'
import { Info, TriangleAlert, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { DURATION, EASE_ENTER, reducedTransition } from '@/lib/motion'
import { cn } from '@/lib/utils'

export type AlertVariant = 'warning' | 'danger' | 'info'

interface AlertBannerProps {
  variant: AlertVariant
  title: string
  description?: string
  actions?: ReactNode
  onDismiss?: () => void
  className?: string
}

const VARIANT_STYLES: Record<AlertVariant, string> = {
  warning: 'border-warning/30 bg-warning/10 text-warning',
  danger: 'border-danger/30 bg-danger/10 text-danger',
  info: 'border-accent/30 bg-accent/10 text-accent-soft',
}

/** Shared banner for a persistent, dismissible condition (preflight degraded, ingestion
 * failed) — distinct from the ephemeral sonner toast and from StateMessage's content-area
 * placeholder. Render it wrapped in the caller's own <AnimatePresence> so the exit animation
 * plays when the condition clears. */
export function AlertBanner({
  variant,
  title,
  description,
  actions,
  onDismiss,
  className,
}: AlertBannerProps) {
  const reduced = useReducedMotion()
  const Icon = variant === 'info' ? Info : TriangleAlert

  return (
    <motion.div
      role={variant === 'danger' ? 'alert' : 'status'}
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={reducedTransition(!!reduced, { duration: DURATION.standard, ease: EASE_ENTER })}
      className={cn(
        'flex items-start gap-3 rounded-lg border px-4 py-3 text-sm',
        VARIANT_STYLES[variant],
        className,
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-foreground">{title}</p>
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
        {actions && <div className="mt-2 flex items-center gap-2">{actions}</div>}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="size-3.5" />
        </button>
      )}
    </motion.div>
  )
}
