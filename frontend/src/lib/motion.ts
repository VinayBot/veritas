import type { Transition } from 'framer-motion'

/**
 * Durations in seconds, mirroring --duration-micro/standard/large in
 * src/styles/tokens.css. Framer Motion takes seconds, CSS takes ms — this is the one
 * JS-side source so the two never drift.
 */
export const DURATION = {
  micro: 0.12,
  standard: 0.2,
  large: 0.32,
} as const

/** Entrance curve, mirrors --ease-enter. */
export const EASE_ENTER: [number, number, number, number] = [0.32, 0.72, 0, 1]
/** Exit curve (ease-in), mirrors --ease-exit. */
export const EASE_EXIT: [number, number, number, number] = [0.4, 0, 1, 1]

/** Snappy spring for small-travel feedback (button press, toggle thumb). */
export const SPRING: Transition = { type: 'spring', stiffness: 300, damping: 20, mass: 0.9 }

/** Softer spring for larger-travel motion (drawer slide, diagram node entrance). */
export const SPRING_SOFT: Transition = { type: 'spring', stiffness: 260, damping: 26, mass: 1 }

/** Standard entrance tween. */
export const TWEEN_ENTER: Transition = { duration: DURATION.standard, ease: EASE_ENTER }

/** List/table stagger: 30ms apart, and only the first ten items animate at all. */
export const STAGGER_STEP = 0.03
export const STAGGER_MAX_ITEMS = 10

export function staggerDelay(index: number): number {
  return index < STAGGER_MAX_ITEMS ? index * STAGGER_STEP : 0
}

/**
 * Swaps any transition for an instant one when the viewer prefers reduced motion. The
 * global CSS rule in index.css collapses CSS transitions; this is the equivalent for
 * Framer-Motion-driven animation, which that rule cannot reach.
 */
export function reducedTransition(reduced: boolean, transition: Transition): Transition {
  return reduced ? { duration: 0 } : transition
}
