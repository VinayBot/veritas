import { motion, useMotionValue, useSpring, useReducedMotion } from 'framer-motion'
import type { HTMLAttributes, PointerEvent as ReactPointerEvent, ReactNode } from 'react'
import { SPRING_SOFT } from '@/lib/motion'
import { cn } from '@/lib/utils'

const MAX_TILT_DEG = 10

// See the matching comment in ui/button.tsx — motion.div's props collide
// with a few native HTMLAttributes names (onDrag*, onAnimation*).
interface TiltCardProps
  extends Omit<
    HTMLAttributes<HTMLDivElement>,
    'className' | 'onDrag' | 'onDragStart' | 'onDragEnd' | 'onAnimationStart' | 'onAnimationEnd'
  > {
  children: ReactNode
  className?: string
}

/**
 * Glass card that tilts in 3D toward the pointer (rotateX/rotateY only —
 * never width/height/top/left), with a soft lift on hover. See
 * docs/UI_MOTION.md for the exact spring preset.
 */
export function TiltCard({ children, className, ...rest }: TiltCardProps) {
  const reduced = useReducedMotion()
  const rotateXRaw = useMotionValue(0)
  const rotateYRaw = useMotionValue(0)
  const rotateX = useSpring(rotateXRaw, SPRING_SOFT)
  const rotateY = useSpring(rotateYRaw, SPRING_SOFT)

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (reduced || event.pointerType === 'touch') return
    const rect = event.currentTarget.getBoundingClientRect()
    const px = (event.clientX - rect.left) / rect.width
    const py = (event.clientY - rect.top) / rect.height
    rotateYRaw.set((px - 0.5) * MAX_TILT_DEG * 2)
    rotateXRaw.set(-(py - 0.5) * MAX_TILT_DEG * 2)
  }

  const handlePointerLeave = () => {
    rotateXRaw.set(0)
    rotateYRaw.set(0)
  }

  return (
    <motion.div
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      whileHover={reduced ? undefined : { scale: 1.02 }}
      transition={SPRING_SOFT}
      style={{ perspective: 800 }}
      className={cn('glass-card p-6', className)}
      {...rest}
    >
      <motion.div style={{ rotateX, rotateY, transformStyle: 'preserve-3d' }}>
        {children}
      </motion.div>
    </motion.div>
  )
}
