import { useEffect, useRef } from 'react'
import { animate, useReducedMotion } from 'framer-motion'
import { DURATION, EASE_ENTER } from '@/lib/motion'

/**
 * Counts from the previous value to the new one. Only animates when the change is
 * meaningful (`minDelta`), so a number that jitters on every poll stays still.
 */
export function CountUp({
  value,
  format = (n) => String(Math.round(n)),
  minDelta = 0,
  className,
}: {
  value: number
  format?: (n: number) => string
  minDelta?: number
  className?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const previous = useRef(value)
  const reduced = useReducedMotion()

  useEffect(() => {
    const from = previous.current
    previous.current = value
    const el = ref.current
    if (!el) return
    if (reduced || Math.abs(value - from) <= minDelta) {
      el.textContent = format(value)
      return
    }
    const controls = animate(from, value, {
      duration: DURATION.large,
      ease: EASE_ENTER,
      onUpdate: (n) => {
        el.textContent = format(n)
      },
    })
    return () => controls.stop()
  }, [value, format, minDelta, reduced])

  return (
    <span ref={ref} className={className}>
      {format(value)}
    </span>
  )
}
