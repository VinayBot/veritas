import { motion, AnimatePresence } from 'framer-motion'
import { Clock, MoreHorizontal } from 'lucide-react'

export type WaitVariant = 'clock' | 'thinking'

/** The two WAIT-pose thought bubbles from the brief: a clock face once a stage has genuinely
 * run past 2s (`sinceMs` is real elapsed time, not a guess), an ellipsis while an LLM call is
 * in flight. Only one is ever shown — real condition, not a decorative loop. */
export function WaitBubble({
  variant,
  visible,
  className,
}: {
  variant: WaitVariant
  visible: boolean
  className?: string
}) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 6, scale: 0.8 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 6, scale: 0.8 }}
          transition={{ duration: 0.2 }}
          className={className}
          data-testid="wait-bubble"
          data-wait-variant={variant}
        >
          <div className="flex items-center gap-1 rounded-full border border-border bg-surface px-2 py-1 shadow-md">
            {variant === 'clock' ? (
              <motion.span
                animate={{ rotate: 360 }}
                transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
                className="flex"
              >
                <Clock className="size-3.5 text-warning" />
              </motion.span>
            ) : (
              <motion.span
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1.1, repeat: Infinity }}
                className="flex"
              >
                <MoreHorizontal className="size-3.5 text-accent" />
              </motion.span>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
