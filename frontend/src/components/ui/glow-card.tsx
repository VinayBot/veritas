import { motion, useMotionValue, useReducedMotion } from 'framer-motion'
import {
  useEffect,
  useRef,
  type HTMLAttributes,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react'
import { subscribeToFrameLoop } from '@/lib/raf-loop'
import { cn } from '@/lib/utils'

// How quickly the glow catches up to the pointer each frame (0-1, higher = snappier).
const LERP_FACTOR = 0.18

interface GlowCardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'className'> {
  children: ReactNode
  className?: string
  contentClassName?: string
}

/**
 * Glass card with a conic/linear gradient border and a soft glow that trails
 * the cursor. The border is the classic padding+background-image trick (an
 * outer element painted with the gradient, a 1px-smaller inner element on
 * top of it) so it works with a rounded radius without border-image's
 * corner artifacts. The glow is a translate-only transform, eased toward the
 * pointer position every frame via the shared rAF loop in lib/raf-loop.ts —
 * see docs/UI_MOTION.md.
 */
export function GlowCard({ children, className, contentClassName, ...rest }: GlowCardProps) {
  const reduced = useReducedMotion()
  const targetRef = useRef({ x: 0, y: 0 })
  const glowX = useMotionValue(0)
  const glowY = useMotionValue(0)
  const unsubscribeRef = useRef<(() => void) | null>(null)

  useEffect(() => () => unsubscribeRef.current?.(), [])

  const startTracking = () => {
    if (reduced || unsubscribeRef.current) return
    unsubscribeRef.current = subscribeToFrameLoop(() => {
      const nextX = glowX.get() + (targetRef.current.x - glowX.get()) * LERP_FACTOR
      const nextY = glowY.get() + (targetRef.current.y - glowY.get()) * LERP_FACTOR
      glowX.set(nextX)
      glowY.set(nextY)
    })
  }

  const stopTracking = () => {
    unsubscribeRef.current?.()
    unsubscribeRef.current = null
  }

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (reduced) return
    const rect = event.currentTarget.getBoundingClientRect()
    targetRef.current = { x: event.clientX - rect.left, y: event.clientY - rect.top }
    startTracking()
  }

  return (
    <div
      onPointerMove={handlePointerMove}
      onPointerLeave={stopTracking}
      className={cn('group relative rounded-[var(--radius-card)] p-px', className)}
      style={{ backgroundImage: 'var(--gradient-border)' }}
      {...rest}
    >
      <div
        className={cn(
          'relative isolate h-full overflow-hidden rounded-[calc(var(--radius-card)-1px)] p-6 shadow-md',
          'bg-[color-mix(in_srgb,var(--color-surface)_70%,transparent)] backdrop-blur-glass',
          contentClassName,
        )}
      >
        {!reduced && (
          <motion.div
            aria-hidden="true"
            className="pointer-events-none absolute top-0 left-0 -z-10 size-64 rounded-full opacity-0 blur-3xl transition-opacity duration-240 group-hover:opacity-100"
            style={{
              backgroundImage: 'var(--gradient-glow)',
              x: glowX,
              y: glowY,
              translateX: '-50%',
              translateY: '-50%',
            }}
          />
        )}
        <div className="relative z-10 h-full">{children}</div>
      </div>
    </div>
  )
}
