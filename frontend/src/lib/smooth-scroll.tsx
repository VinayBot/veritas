import { ReactLenis } from 'lenis/react'
import { useReducedMotion } from 'framer-motion'
import type { ReactNode } from 'react'

/**
 * Lenis smooth scroll for the landing page only. The app's own screens are panels with their
 * own scroll containers, where hijacking the wheel caused real bugs (docs/TROUBLESHOOTING.md),
 * so they use native scrolling. Skipped entirely under prefers-reduced-motion.
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
