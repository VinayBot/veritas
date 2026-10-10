import { ReactLenis } from 'lenis/react'
import { useReducedMotion } from 'framer-motion'
import type { ReactNode } from 'react'

/**
 * App-wide Lenis smooth scroll (the brief's STACK list; GSAP ScrollTrigger
 * is explicitly scoped to a landing page that doesn't exist yet, so it's
 * installed but unused — see docs/UI_MOTION.md). Smooth-scroll hijacking is
 * itself a motion effect, so it's skipped entirely under
 * prefers-reduced-motion rather than just running at a shorter duration.
 */
export function SmoothScroll({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion()

  if (reduced) return <>{children}</>

  return (
    <ReactLenis root options={{ lerp: 0.1, duration: 1.1 }}>
      {children}
    </ReactLenis>
  )
}
