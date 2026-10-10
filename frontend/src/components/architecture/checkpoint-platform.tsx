import { motion, useReducedMotion } from 'framer-motion'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export type CheckpointStatus = 'pending' | 'active' | 'done' | 'error'

interface CheckpointPlatformProps {
  index: number
  label: string
  status: CheckpointStatus
  tall?: boolean
  onClick?: () => void
}

/** A numbered teal cylinder platform (design-refs/robot-journey.png's visual language — see
 * docs/DECISIONS.md: the reference assets weren't present on disk, so this was built from the
 * brief's written description per its own fallback rule). A dashed ring orbits the platform
 * while its checkpoint is active and morphs into a check on completion — driven by real
 * `status`, never a timer. */
export function CheckpointPlatform({ index, label, status, tall, onClick }: CheckpointPlatformProps) {
  const reduced = useReducedMotion()
  const height = tall ? 54 : 22

  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={`checkpoint-platform-${index}`}
      data-checkpoint-status={status}
      className="group flex flex-col items-center gap-2 bg-transparent"
    >
      <div className="relative flex size-20 items-center justify-center">
        {status === 'active' && (
          <motion.svg
            className="absolute inset-0"
            viewBox="0 0 80 80"
            animate={reduced ? undefined : { rotate: 360 }}
            transition={reduced ? undefined : { duration: 2.4, repeat: Infinity, ease: 'linear' }}
          >
            <circle
              cx={40}
              cy={40}
              r={36}
              fill="none"
              stroke="var(--color-accent)"
              strokeWidth={3}
              strokeDasharray="18 10"
              strokeLinecap="round"
            />
          </motion.svg>
        )}
        <div
          className={cn(
            'flex size-14 items-center justify-center rounded-full border-2 text-lg font-semibold shadow-md transition-colors',
            status === 'done' && 'border-success bg-success/15 text-success',
            status === 'active' && 'border-accent bg-accent/15 text-accent-soft',
            status === 'pending' && 'border-border bg-surface-raised text-muted-foreground',
            status === 'error' && 'border-danger bg-danger/15 text-danger',
          )}
        >
          {status === 'done' ? <Check className="size-6" /> : index}
        </div>
      </div>
      <span
        className={cn(
          'max-w-24 text-center text-xs font-medium',
          status === 'pending' ? 'text-muted-foreground' : 'text-foreground',
        )}
      >
        {label}
      </span>
      {/* The teal cylinder "platform" the character stands on — height varies to produce the
          zigzag silhouette (1 low, 2 high, 3 low, ...) from the reference description. */}
      <div
        className="w-16 rounded-t-md"
        style={{
          height,
          background: 'linear-gradient(180deg, #2dd4bf 0%, #0f9c8c 100%)',
        }}
      />
    </button>
  )
}
