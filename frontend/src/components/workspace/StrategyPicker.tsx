import { useState } from 'react'
import { toast } from 'sonner'
import { Check, ChevronDown, Hammer, Layers, Star } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ProgressBar } from '@/components/ui/progress-bar'
import { ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { useJob } from '@/hooks/useJob'
import { getStrategies, prepareStrategy, setDocumentStrategy } from '@/lib/api/client'
import type { StrategiesResponse, Strategy } from '@/lib/api/types'
import { ms } from '@/lib/format'
import { cn } from '@/lib/utils'

const COST_LABEL: Record<Strategy['relative_cost'], string> = {
  low: 'low cost',
  medium: 'medium cost',
  high: 'high cost',
  very_high: 'very high cost',
}

function latencyLabel(s: Strategy): { text: string; verified: boolean } {
  return s.measured_latency_ms !== null
    ? { text: `${ms(s.measured_latency_ms)} measured over ${s.measured_runs} answers`, verified: true }
    : { text: `~${ms(s.typical_latency_ms)} estimated`, verified: false }
}

/**
 * Pick the RAG strategy for upcoming questions, or change the workspace default. Each row
 * shows whether the strategy can run right now; one that needs something built offers to
 * build it and shows the real progress.
 */
export function StrategyPicker({
  documentId,
  data,
  error,
  selected,
  onSelect,
  onChanged,
}: {
  documentId: string | null
  data: StrategiesResponse | null
  error: unknown
  /** Strategy chosen for upcoming questions; null = follow the default. */
  selected: string | null
  onSelect: (id: string | null) => void
  onChanged: (next?: StrategiesResponse) => void
}) {
  const [open, setOpen] = useState(false)
  const [buildJob, setBuildJob] = useState<{ id: string; strategy: string } | null>(null)
  const job = useJob(buildJob?.id ?? null, (finished) => {
    if (finished.status === 'done') toast.success('Ready to use')
    else if (finished.status === 'failed') toast.error(finished.error ?? 'Build failed')
    setBuildJob(null)
    onChanged()
  })

  const active = data?.strategies.find((s) => s.id === (selected ?? data.default))

  async function handleBuild(strategy: Strategy) {
    if (!documentId) return
    try {
      const { job_id } = await prepareStrategy(strategy.id, documentId)
      setBuildJob({ id: job_id, strategy: strategy.id })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not start the build')
    }
  }

  async function handleDefault(strategy: Strategy) {
    try {
      if (!documentId) return
      await setDocumentStrategy(documentId, strategy.id)
      onSelect(null)
      onChanged(await getStrategies(documentId))
      toast.success(`${strategy.display_name} now answers this document`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not change the default')
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" data-testid="strategy-picker" className="max-w-56">
          <Layers className="size-3.5 shrink-0 text-accent" />
          <span className="truncate">{active ? active.display_name : 'Strategy'}</span>
          {selected === null && active && <span className="text-[10px] text-muted-foreground">default</span>}
          <ChevronDown className="size-3 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[26rem] p-2" align="start" data-testid="strategy-list">
        <p className="px-2 pt-1 pb-2 text-[11px] text-muted-foreground">
          How answers are found. Takes effect on your next question — nothing restarts and the document is not re-ingested.
        </p>
        {error ? (
          <ErrorState error={error} compact />
        ) : !data ? (
          <LoadingState shape="lines" rows={6} label="Loading strategies" className="p-2" />
        ) : (
          <ul className="flex max-h-[60vh] flex-col gap-1 overflow-y-auto" data-lenis-prevent>
            {data.strategies.map((s) => {
              const isActive = s.id === active?.id
              const building = buildJob?.strategy === s.id
              const latency = latencyLabel(s)
              return (
                <li key={s.id} data-testid={`strategy-option-${s.id}`} data-available={s.available}>
                  <div
                    className={cn(
                      'rounded-lg border p-2.5 transition-colors duration-micro',
                      isActive ? 'border-accent/60 bg-accent/10' : 'border-transparent hover:bg-surface-raised',
                      !s.available && 'opacity-80',
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <button
                        type="button"
                        disabled={!s.available}
                        onClick={() => {
                          onSelect(s.is_default ? null : s.id)
                          setOpen(false)
                        }}
                        className="min-w-0 flex-1 text-left disabled:cursor-not-allowed"
                      >
                        <span className="flex flex-wrap items-center gap-1.5">
                          <span className="text-sm font-semibold text-foreground">{s.display_name}</span>
                          {s.is_default && <Badge variant="glow">default</Badge>}
                          {isActive && <Check className="size-3.5 text-success" aria-label="selected" />}
                        </span>
                        <span className="mt-0.5 block text-xs text-muted-foreground">{s.description}</span>
                        <span className="mt-1 flex flex-wrap gap-x-2 text-[11px] text-muted-foreground">
                          <span>Best for: <span className="text-foreground">{s.best_for.toLowerCase()}</span></span>
                        </span>
                        <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px]">
                          <span className={cn('rounded-pill px-1.5 py-0.5', latency.verified ? 'bg-success/15 text-success' : 'bg-surface text-muted-foreground')}>
                            {latency.text}
                          </span>
                          <span className="rounded-pill bg-surface px-1.5 py-0.5 text-muted-foreground">{COST_LABEL[s.relative_cost]}</span>
                        </span>
                      </button>
                      {s.available && !s.is_default && (
                        <Button variant="ghost" size="icon-sm" aria-label={`Use ${s.display_name} for this document`} title="Use for this document" onClick={() => void handleDefault(s)}>
                          <Star className="size-3.5" />
                        </Button>
                      )}
                    </div>
                    {!s.available && (
                      <div className="mt-2 rounded-md bg-warning/10 p-2 text-[11px] text-foreground" data-testid={`strategy-unavailable-${s.id}`}>
                        <p>{s.unavailable_reason}</p>
                        {building ? (
                          <div className="mt-2 flex flex-col gap-1">
                            <ProgressBar value={job.progress} label={`Building for ${s.display_name}`} tone="live" />
                            <span className="text-muted-foreground">{job.message}</span>
                          </div>
                        ) : (
                          s.action &&
                          documentId && (
                            <Button size="xs" className="mt-2" onClick={() => void handleBuild(s)} disabled={buildJob !== null} data-testid={`strategy-build-${s.id}`}>
                              <Hammer className="size-3" />
                              {s.action === 'build_index' ? 'Build the index it needs' : 'Build the knowledge graph'}
                            </Button>
                          )
                        )}
                      </div>
                    )}
                    {s.available && s.warning && <p className="mt-1.5 text-[11px] text-warning">{s.warning}</p>}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  )
}
