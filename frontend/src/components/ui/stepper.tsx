import { motion, useReducedMotion } from 'framer-motion'
import { Check, X } from 'lucide-react'
import { EASE_OUT, DURATION } from '@/lib/motion'
import { Skeleton } from './skeleton'
import { StateMessage, type ComponentStatus } from './state-message'
import { cn } from '@/lib/utils'

export type StepState = 'pending' | 'active' | 'complete' | 'error'

export interface StepperStep {
  id: string
  title: string
  description?: string
  state?: StepState
}

interface StepperProps {
  steps: StepperStep[]
  /** Overall data status — distinct from each step's own `state`. */
  status?: ComponentStatus
  orientation?: 'horizontal' | 'vertical'
  emptyDescription?: string
  errorDescription?: string
  className?: string
}

/**
 * A sequence of steps with a per-step state (pending/active/complete/error)
 * plus the shared loading/empty/error/success contract for the sequence as a
 * whole — e.g. "loading" while the step list itself is still being fetched,
 * independent of which individual step is currently active.
 */
export function Stepper({
  steps,
  status = 'success',
  orientation = 'horizontal',
  emptyDescription,
  errorDescription,
  className,
}: StepperProps) {
  const reduced = useReducedMotion()
  const isVertical = orientation === 'vertical'

  if (status === 'loading') {
    return (
      <div
        className={cn('flex gap-4', isVertical ? 'flex-col' : 'flex-row items-start', className)}
        role="status"
        aria-label="Loading steps"
      >
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className={cn('flex min-w-0 flex-1 items-center gap-3', isVertical && 'flex-row')}
          >
            <Skeleton className="size-8 shrink-0 rounded-full" />
            {/* w-full + max-w (not a fixed w-*) so this shrinks instead of
                forcing a minimum row width narrower viewports can't satisfy. */}
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-3 w-full max-w-20" />
              <Skeleton className="h-2.5 w-full max-w-28" />
            </div>
          </div>
        ))}
      </div>
    )
  }

  if (status === 'empty' || status === 'error') {
    return (
      <StateMessage
        status={status}
        title={status === 'empty' ? 'No steps yet' : 'Could not load steps'}
        description={status === 'empty' ? emptyDescription : errorDescription}
        className={className}
      />
    )
  }

  const completeCount = steps.filter((step) => step.state === 'complete').length

  return (
    <ol
      className={cn('relative flex', isVertical ? 'flex-col gap-6' : 'flex-row gap-2', className)}
      aria-label="Progress"
    >
      {steps.map((step, index) => {
        const state = step.state ?? 'pending'
        const isLast = index === steps.length - 1
        const segmentFilled = index < completeCount

        return (
          <li
            key={step.id}
            className={cn(
              'relative flex min-w-0 flex-1',
              isVertical ? 'flex-row gap-3' : 'flex-col items-center gap-2',
            )}
            aria-current={state === 'active' ? 'step' : undefined}
          >
            <div className={cn('flex items-center', isVertical ? 'flex-col' : 'w-full flex-row')}>
              <StepIndicator state={state} index={index} reduced={!!reduced} />
              {!isLast && (
                <div
                  className={cn(
                    'relative min-w-2 bg-border',
                    isVertical ? 'mt-1 ml-4 w-px flex-1' : 'mx-1 h-px flex-1',
                  )}
                >
                  <motion.div
                    className={cn('absolute inset-0 bg-accent', isVertical ? 'w-px' : 'h-px')}
                    style={{ transformOrigin: isVertical ? 'top' : 'left' }}
                    initial={false}
                    animate={isVertical ? { scaleY: segmentFilled ? 1 : 0 } : { scaleX: segmentFilled ? 1 : 0 }}
                    transition={{ duration: reduced ? 0 : DURATION.slow, ease: EASE_OUT }}
                  />
                </div>
              )}
            </div>
            <div className={cn('min-w-0 text-center', isVertical && 'pb-2 text-left')}>
              <p
                className={cn(
                  'text-sm font-medium',
                  state === 'error' ? 'text-danger' : 'text-foreground',
                )}
              >
                {step.title}
              </p>
              {step.description && (
                <p className="text-xs text-muted-foreground">{step.description}</p>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function StepIndicator({
  state,
  index,
  reduced,
}: {
  state: StepState
  index: number
  reduced: boolean
}) {
  return (
    <motion.div
      aria-hidden="true"
      className={cn(
        'flex size-8 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums',
        state === 'complete' && 'border-accent bg-accent text-on-accent',
        state === 'active' && 'border-accent text-accent',
        state === 'pending' && 'border-border text-muted-foreground',
        state === 'error' && 'border-danger bg-danger/10 text-danger',
      )}
      animate={{ scale: state === 'active' ? 1.1 : 1 }}
      transition={{ duration: reduced ? 0 : DURATION.fast, ease: EASE_OUT }}
    >
      {state === 'complete' ? (
        <Check className="size-4" />
      ) : state === 'error' ? (
        <X className="size-4" />
      ) : (
        index + 1
      )}
    </motion.div>
  )
}
