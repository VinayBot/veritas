import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion, animate } from 'framer-motion'
import { cn } from '@/lib/utils'

export interface RingSegment {
  label: string
  value: number
  color: string
}

export interface RingDataset {
  key: string
  label: string
  segments: RingSegment[]
  centerLabel: string
  centerValue: number
}

const RADIUS = 70
const STROKE = 16
const CIRCUMFERENCE = 2 * Math.PI * RADIUS
const GAP_DEG = 3

/** The donut-ring.png visual target (design-refs/ wasn't present on disk — built from the
 * brief's written description, per its own fallback rule; see docs/DECISIONS.md): a thick
 * gradient ring with gaps between segments, a thin inner ring, a centered count-up number,
 * and a percentage legend. Every value here comes from the real document — see call sites. */
export function RingHero({ datasets }: { datasets: RingDataset[] }) {
  const [activeKey, setActiveKey] = useState(datasets[0]?.key)
  const active = datasets.find((d) => d.key === activeKey) ?? datasets[0]
  const [hovered, setHovered] = useState<string | null>(null)
  const reduced = useReducedMotion()
  const numberRef = useRef<HTMLSpanElement>(null)

  const total = active?.segments.reduce((sum, s) => sum + s.value, 0) ?? 0
  const arcs = useMemo(() => {
    if (!active || total === 0) return []
    let cumulativeDeg = 0
    return active.segments.map((seg) => {
      const fraction = seg.value / total
      const degrees = fraction * 360
      const startDeg = cumulativeDeg
      cumulativeDeg += degrees
      const visibleDeg = Math.max(0, degrees - GAP_DEG)
      return { ...seg, fraction, startDeg, visibleDeg }
    })
  }, [active, total])

  function animateCenter(target: number) {
    if (!numberRef.current) return
    const node = numberRef.current
    animate(0, target, {
      duration: reduced ? 0 : 0.8,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => {
        node.textContent = Math.round(v).toLocaleString()
      },
    })
  }

  // Must be useEffect, not useMemo: refs attach during the commit phase, which runs AFTER
  // render — a ref read inside useMemo (which runs *during* render) is reliably still null on
  // the first pass, so the count-up silently never started. useEffect runs post-commit, when
  // numberRef.current is guaranteed to exist.
  useEffect(() => {
    animateCenter(active?.centerValue ?? 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run only when the active dataset (or its value) actually changes
  }, [active?.key, active?.centerValue])

  if (!active) return null

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:justify-center" data-testid="ring-hero">
      <div className="relative size-44 shrink-0">
        <svg viewBox="0 0 180 180" className="size-full -rotate-90">
          <circle cx={90} cy={90} r={RADIUS - STROKE / 2 - 6} fill="none" stroke="var(--color-border)" strokeWidth={1} />
          {arcs.map((arc, i) => (
            <motion.circle
              key={arc.label}
              cx={90}
              cy={90}
              r={RADIUS}
              fill="none"
              stroke={arc.color}
              strokeWidth={hovered === arc.label ? STROKE + 4 : STROKE}
              strokeLinecap="round"
              strokeDasharray={`${(arc.visibleDeg / 360) * CIRCUMFERENCE} ${CIRCUMFERENCE}`}
              initial={false}
              animate={{
                strokeDashoffset: -((arc.startDeg / 360) * CIRCUMFERENCE),
                opacity: hovered && hovered !== arc.label ? 0.35 : 1,
              }}
              transition={{ duration: reduced ? 0 : 0.7, ease: [0.16, 1, 0.3, 1], delay: reduced ? 0 : i * 0.06 }}
              onMouseEnter={() => setHovered(arc.label)}
              onMouseLeave={() => setHovered(null)}
              style={{ cursor: 'pointer' }}
            />
          ))}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span ref={numberRef} className="font-display text-3xl font-semibold text-foreground tabular-nums">
            0
          </span>
          <span className="text-xs text-muted-foreground">{active.centerLabel}</span>
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-3">
        {datasets.length > 1 && (
          <div className="flex flex-wrap gap-1 rounded-full bg-surface-raised p-1">
            {datasets.map((d) => (
              <button
                key={d.key}
                type="button"
                onClick={() => setActiveKey(d.key)}
                data-testid={`ring-dataset-${d.key}`}
                className={cn(
                  'rounded-full px-2.5 py-1 text-xs font-medium transition-colors',
                  activeKey === d.key ? 'bg-accent text-on-accent' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {d.label}
              </button>
            ))}
          </div>
        )}
        <ul className="flex flex-col gap-1.5">
          {active.segments.map((seg) => {
            const pct = total > 0 ? (seg.value / total) * 100 : 0
            return (
              <li
                key={seg.label}
                className="flex items-center gap-2 text-sm"
                onMouseEnter={() => setHovered(seg.label)}
                onMouseLeave={() => setHovered(null)}
              >
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: seg.color }} />
                <span className="min-w-0 flex-1 truncate text-foreground">{seg.label}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">{pct.toFixed(0)}%</span>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
