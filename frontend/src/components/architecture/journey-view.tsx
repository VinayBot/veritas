import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { RobotCharacter } from '@/components/robot/robot-character'
import { CheckpointPlatform, type CheckpointStatus } from '@/components/architecture/checkpoint-platform'
import { WaitBubble } from '@/components/architecture/wait-bubble'
import type { TraceEvent } from '@/lib/api/types'

export interface CheckpointDef {
  id: string
  label: string
  stages: string[]
  /** Stages required for this checkpoint to count as "done" — defaults to all of `stages`.
   * Checkpoint 3 ("Understand") only requires chunk/embed/index: graph/profile/advisor are
   * background enrichment (see docs/TROUBLESHOOTING.md) that must never block the journey
   * from reaching "done" the same way it never blocks chat-readiness. */
  requiredStages?: string[]
  source: 'ingestion' | 'chat'
  llmHeavy?: boolean
}

// Real stage order is upload -> parse -> refine -> pii_vault -> chunk -> embed -> index ->
// graph -> profile -> advisor; the brief's own example groups "parse" under checkpoint 3
// alongside chunk/embed/index, but parse genuinely runs before refine, and "the robot is
// never at step N+1 before step N is done" is an explicit hard rule in both briefs — so parse
// moved to checkpoint 1 here. Recorded in docs/DECISIONS.md.
export const JOURNEY_CHECKPOINTS: CheckpointDef[] = [
  { id: 'cp1', label: 'Upload & Deliver', stages: ['upload', 'parse'], source: 'ingestion' },
  { id: 'cp2', label: 'Refine & Protect', stages: ['refine', 'pii_vault'], source: 'ingestion' },
  {
    id: 'cp3',
    label: 'Understand',
    stages: ['chunk', 'embed', 'index', 'graph', 'profile', 'advisor'],
    requiredStages: ['chunk', 'embed', 'index'],
    source: 'ingestion',
  },
  {
    id: 'cp4',
    label: 'Retrieve & Reason',
    stages: ['guardian_in', 'semantic_cache', 'planner', 'rewriter', 'retriever', 'critic'],
    source: 'chat',
    llmHeavy: true,
  },
  {
    id: 'cp5',
    label: 'Answer & Celebrate',
    stages: ['synthesizer', 'verifier', 'guardian_out'],
    source: 'chat',
    llmHeavy: true,
  },
]

// Zigzag per the brief: 1 low, 2 high, 3 low, 4 high, 5 low.
const LAYOUT = [
  { x: 70, y: 290, tall: false },
  { x: 230, y: 150, tall: true },
  { x: 390, y: 290, tall: false },
  { x: 550, y: 150, tall: true },
  { x: 710, y: 290, tall: false },
]

const SLOW_STAGE_MS = 2000

function latestEventFor(stageId: string, ingestionEvents: TraceEvent[], chatEvents: TraceEvent[], source: 'ingestion' | 'chat'): TraceEvent | undefined {
  const pool = source === 'ingestion' ? ingestionEvents : chatEvents
  const matching = pool.filter((e) => e.stage === stageId)
  return matching[matching.length - 1]
}

/** Computes all 5 statuses together, not independently, because "done" needs a look-ahead:
 * different code paths exercise different subsets of a checkpoint's stages (a cache HIT only
 * ever fires "semantic_cache"; a cache MISS fires guardian_in/planner/rewriter/retriever/
 * critic and never touches "semantic_cache" at all), so "every listed stage reached done" is
 * too strict and would stay stuck forever on whichever stage this run happened not to use.
 * The pipeline is strictly sequential, so if a LATER checkpoint has any event at all, this
 * one must already be done regardless of which of its own stages fired — that look-ahead is
 * what actually makes "done" robust across modes. requiredStages (e.g. checkpoint 3's
 * chunk/embed/index) still covers the case where there's no later activity to look ahead to
 * yet but the stage genuinely finished (ingestion's optional graph/profile/advisor lagging). */
function computeStatuses(ingestionEvents: TraceEvent[], chatEvents: TraceEvent[]): CheckpointStatus[] {
  const raw = JOURNEY_CHECKPOINTS.map((cp) => {
    const events = cp.stages.map((s) => latestEventFor(s, ingestionEvents, chatEvents, cp.source))
    const required = (cp.requiredStages ?? cp.stages).map((s) =>
      latestEventFor(s, ingestionEvents, chatEvents, cp.source),
    )
    return {
      hasError: events.some((e) => e?.status === 'error' || e?.status === 'blocked'),
      hasAnyEvent: events.some((e) => e !== undefined),
      requiredAllDone: required.length > 0 && required.every((e) => e?.status === 'done'),
      hasRunning: events.some((e) => e?.status === 'running' || e?.status === 'retrying'),
    }
  })

  return raw.map((r, i) => {
    if (r.hasError) return 'error'
    const laterStarted = raw.slice(i + 1).some((later) => later.hasAnyEvent)
    if (laterStarted || r.requiredAllDone) return 'done'
    if (r.hasRunning) return 'active'
    return 'pending'
  })
}

/** Real "how long has this exact stage been running" — not a guess — compares against the
 * event's own `started_at`, which only exists once the backend genuinely started that stage. */
function currentStageElapsedMs(cp: CheckpointDef, ingestionEvents: TraceEvent[], chatEvents: TraceEvent[], now: number): { stage: string; ms: number } | null {
  for (const stageId of cp.stages) {
    const event = latestEventFor(stageId, ingestionEvents, chatEvents, cp.source)
    if (event?.status === 'running') {
      // Clamped at 0 — `now` only ticks every 500ms (see the interval above), so a stage that
      // started within the last tick can otherwise render a brief, meaningless negative value.
      return { stage: stageId, ms: Math.max(0, now - new Date(event.started_at).getTime()) }
    }
  }
  return null
}

export function JourneyView({
  ingestionEvents,
  chatEvents,
  fileLabel,
  onSelectCheckpoint,
}: {
  ingestionEvents: TraceEvent[]
  chatEvents: TraceEvent[]
  fileLabel: string | null
  onSelectCheckpoint: (cp: CheckpointDef) => void
}) {
  const reduced = useReducedMotion()
  const [now, setNow] = useState(() => Date.now())
  const prevIndexRef = useRef(0)

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(interval)
  }, [])

  const statuses = useMemo(
    () => computeStatuses(ingestionEvents, chatEvents),
    [ingestionEvents, chatEvents],
  )

  // Never advance past the last checkpoint that's actually started — a document finishing
  // ingestion (1-3 done) must not jump the robot to checkpoint 4 before a chat message has
  // genuinely put it in an 'active' state. The robot rests at the last completed checkpoint
  // until the next one really begins; this is exactly what "never at step N+1 before step N
  // is done" means in the event-count sense, not just a UI nicety.
  //
  // Checkpoint 3's enrichment (graph/profile/advisor) and a chat turn's checkpoints 4-5 can
  // be genuinely active *simultaneously* — enrichment is a background phase that never blocks
  // chat (see docs/TROUBLESHOOTING.md). When both are active, the chat turn is what the user
  // is actually looking at, so prefer the highest-index active checkpoint, not the first.
  const currentIndex = useMemo(() => {
    const errorIdx = statuses.findIndex((s) => s === 'error')
    if (errorIdx !== -1) return errorIdx
    let lastActive = -1
    statuses.forEach((s, i) => {
      if (s === 'active') lastActive = i
    })
    if (lastActive !== -1) return lastActive
    return Math.max(0, statuses.lastIndexOf('done'))
  }, [statuses])

  const isWalking = currentIndex !== prevIndexRef.current
  useEffect(() => {
    const t = window.setTimeout(() => {
      prevIndexRef.current = currentIndex
    }, 650)
    return () => window.clearTimeout(t)
  }, [currentIndex])

  const activeCp = JOURNEY_CHECKPOINTS[currentIndex]
  const activeStatus = statuses[currentIndex]
  const stageInfo = currentStageElapsedMs(activeCp, ingestionEvents, chatEvents, now)
  const allDone = statuses.every((s) => s === 'done')
  const hasError = statuses.some((s) => s === 'error')

  const robotState = hasError
    ? 'error'
    : allDone
      ? 'celebrate'
      : isWalking && !reduced
        ? 'walk'
        : activeStatus === 'active'
          ? 'working'
          : 'idle'

  const pos = LAYOUT[currentIndex]
  const carrying = currentIndex === 0 && fileLabel ? { label: fileLabel } : null

  const chipText = hasError
    ? `${activeCp.label} • Error`
    : allDone
      ? 'Mission complete!'
      : isWalking
        ? `Walking to checkpoint ${currentIndex + 1}`
        : stageInfo
          ? `Checkpoint ${currentIndex + 1} • ${stageInfo.stage} (${(stageInfo.ms / 1000).toFixed(1)}s)`
          : `Checkpoint ${currentIndex + 1} • ${activeCp.label}`

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border border-border bg-gradient-to-b from-accent/5 to-surface" data-testid="journey-view">
      <div
        className="absolute top-4 left-4 z-10 rounded-full border border-border bg-surface/90 px-3 py-1.5 text-xs font-medium text-foreground shadow-md backdrop-blur"
        data-testid="journey-status-chip"
      >
        {chipText}
      </div>

      <svg viewBox="0 0 800 380" className="h-full w-full">
        <path
          d={LAYOUT.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x + 32} ${p.y - 10}`).join(' ')}
          fill="none"
          stroke="var(--color-accent)"
          strokeWidth={3}
          strokeDasharray="2 10"
          strokeLinecap="round"
          opacity={0.5}
        />
      </svg>

      <div className="absolute inset-0">
        {LAYOUT.map((p, i) => (
          <div key={JOURNEY_CHECKPOINTS[i].id} style={{ position: 'absolute', left: p.x, top: p.y }}>
            <CheckpointPlatform
              index={i + 1}
              label={JOURNEY_CHECKPOINTS[i].label}
              status={statuses[i]}
              tall={p.tall}
              onClick={() => onSelectCheckpoint(JOURNEY_CHECKPOINTS[i])}
            />
          </div>
        ))}

        <motion.div
          className="absolute"
          data-testid="robot-journey-position"
          animate={{ left: pos.x + 2, top: pos.y - 70 }}
          transition={{ duration: reduced ? 0.001 : 0.6, ease: 'easeInOut' }}
        >
          <RobotCharacter
            state={robotState}
            facing={pos.x >= (LAYOUT[prevIndexRef.current]?.x ?? pos.x) ? 'right' : 'left'}
            carrying={carrying}
            action={activeCp.id}
          />
          <WaitBubble
            variant="clock"
            visible={!hasError && !allDone && !isWalking && !!stageInfo && stageInfo.ms > SLOW_STAGE_MS}
            className="absolute -top-2 -right-6"
          />
          <WaitBubble
            variant="thinking"
            visible={!hasError && !allDone && !isWalking && !!activeCp.llmHeavy && activeStatus === 'active'}
            className="absolute -top-2 -right-6"
          />
        </motion.div>
      </div>
    </div>
  )
}
