import type { Transition } from 'framer-motion'

/**
 * Durations in seconds, mirroring the --duration-120/240/480/800 tokens in
 * src/index.css. Framer Motion transitions take seconds, CSS takes ms — this
 * is the one JS-side source of truth so the two never drift apart.
 */
export const DURATION = {
  fast: 0.12,
  base: 0.24,
  slow: 0.48,
  slower: 0.8,
} as const

/** Snappy, slightly-overshooting spring for small-travel feedback (button press, badge pop, tilt settle). */
export const SPRING: Transition = { type: 'spring', stiffness: 300, damping: 20, mass: 0.9 }

/** Softer, more damped spring for larger-travel motion (drawer slide, gauge sweep, stepper progress). */
export const SPRING_SOFT: Transition = { type: 'spring', stiffness: 180, damping: 24, mass: 1 }

/** Standard "ease-out" deceleration curve, mirrors --ease-out in src/index.css. */
export const EASE_OUT: [number, number, number, number] = [0.16, 1, 0.3, 1]

/** Plain tween using EASE_OUT, for fades/slides that shouldn't spring. */
export const TWEEN_BASE: Transition = { duration: DURATION.base, ease: EASE_OUT }

/**
 * Swaps any transition for a near-instant one when the viewer prefers reduced
 * motion. The global CSS rule in index.css already collapses CSS transitions;
 * this is the equivalent for Framer-Motion-driven transform/opacity animation,
 * which that CSS rule cannot reach.
 */
export function reducedTransition(reduced: boolean, transition: Transition): Transition {
  return reduced ? { duration: 0.001 } : transition
}
