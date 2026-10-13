import { Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import { cn } from '@/lib/utils'
import { LIGHT_FLOW_STAGES } from './lightFlowStages'

export type LightFlowSpeed = 0.5 | 1 | 2

interface LightFlowDockProps {
  mode: 'tour' | 'live'
  activeStageId: number
  playing: boolean
  speed: LightFlowSpeed
  onPlayPause: () => void
  onPrev: () => void
  onNext: () => void
  onSpeedChange: (speed: LightFlowSpeed) => void
  onSelectStage: (stageId: number) => void
}

/** LF-4: five numbered stage pills + playback controls + a one-line description. Only
 * meaningful in Tour mode — Live mode's "stage" is whatever a real trace event says, so this
 * dock is read-only there (no play/pause/prev/next; the active pill just follows reality). */
export function LightFlowDock({
  mode,
  activeStageId,
  playing,
  speed,
  onPlayPause,
  onPrev,
  onNext,
  onSpeedChange,
  onSelectStage,
}: LightFlowDockProps) {
  const activeStage = LIGHT_FLOW_STAGES.find((s) => s.id === activeStageId) ?? LIGHT_FLOW_STAGES[0]

  return (
    <div
      className="theme-arch pointer-events-auto flex flex-col gap-2 rounded-xl border border-white/10 bg-black/70 px-4 py-3 backdrop-blur"
      data-testid="light-flow-dock"
      role="group"
      aria-label="Light flow stepper"
    >
      <div className="flex items-center gap-3">
        {mode === 'tour' && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={onPrev}
              aria-label="Previous stage"
              className="rounded-full p-1.5 text-white/70 hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
            >
              <SkipBack className="size-4" />
            </button>
            <button
              type="button"
              onClick={onPlayPause}
              aria-label={playing ? 'Pause demo flow' : 'Play demo flow'}
              data-testid="light-flow-play-pause"
              className="rounded-full bg-white/10 p-2 text-white hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
            >
              {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
            </button>
            <button
              type="button"
              onClick={onNext}
              aria-label="Next stage"
              className="rounded-full p-1.5 text-white/70 hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
            >
              <SkipForward className="size-4" />
            </button>
          </div>
        )}

        <div className="flex items-center gap-1.5" role="tablist" aria-label="Light flow stages">
          {LIGHT_FLOW_STAGES.map((stage) => {
            const isActive = stage.id === activeStageId
            return (
              <button
                key={stage.id}
                type="button"
                role="tab"
                aria-selected={isActive}
                data-testid={`light-flow-stage-${stage.id}`}
                onClick={() => mode === 'tour' && onSelectStage(stage.id)}
                className={cn(
                  'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-opacity',
                  isActive ? 'opacity-100' : 'opacity-25',
                  mode === 'tour' ? 'cursor-pointer' : 'cursor-default',
                )}
                style={{ borderColor: stage.color, color: isActive ? stage.color : '#fff' }}
                disabled={mode === 'live'}
              >
                <span
                  className="flex size-4 items-center justify-center rounded-full text-[10px] font-bold"
                  style={{ background: stage.color, color: '#07060b' }}
                >
                  {stage.id}
                </span>
                {stage.name}
              </button>
            )
          })}
        </div>

        {mode === 'tour' && (
          <div className="ml-auto flex items-center gap-1 text-[11px] text-white/60">
            {([0.5, 1, 2] as LightFlowSpeed[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onSpeedChange(s)}
                aria-pressed={speed === s}
                className={cn(
                  'rounded px-1.5 py-0.5 font-mono',
                  speed === s ? 'bg-white/20 text-white' : 'hover:bg-white/10',
                )}
              >
                {s}&times;
              </button>
            ))}
          </div>
        )}
        {mode === 'live' && (
          <span className="ml-auto rounded-full bg-[color:var(--color-accent)]/20 px-2 py-0.5 text-[11px] font-medium text-[color:var(--color-accent)]">
            Live
          </span>
        )}
      </div>
      <p className="text-[11px] text-white/50" data-testid="light-flow-description">
        {activeStage.description}
      </p>
    </div>
  )
}
