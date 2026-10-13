import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, GitCompareArrows, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ProgressBar } from '@/components/ui/progress-bar'
import { Skeleton } from '@/components/ui/skeleton'
import { useJob } from '@/hooks/useJob'
import { getRecommendation, prepareStrategy, setDefaultStrategy } from '@/lib/api/client'
import type { Recommendation } from '@/lib/api/types'
import { ImprovementPanel } from './ImprovementPanel'
import { cn } from '@/lib/utils'

const previousKey = (documentId: string) => `veritas:previous-strategy:${documentId}`

function readPrevious(documentId: string): string | null {
  try {
    return window.localStorage.getItem(previousKey(documentId))
  } catch {
    return null
  }
}

function writePrevious(documentId: string, strategy: string) {
  try {
    window.localStorage.setItem(previousKey(documentId), strategy)
  } catch {
    // Without storage the improvement is measured against plain hybrid search instead.
  }
}

/**
 * Shown once a document is ingested: the strategy the rule set recommends for it, why (each
 * reason quotes something measured from the document), and one button to start using it.
 */
export function RecommendationCard({
  documentId,
  enrichmentStatus,
  onApplied,
  onCompare,
  nameOf,
}: {
  documentId: string
  /** The recommendation is re-read when background graph building finishes. */
  enrichmentStatus: string | null
  onApplied: () => void
  onCompare: (strategies: string[]) => void
  nameOf?: (id: string) => string
}) {
  const [rec, setRec] = useState<Recommendation | null>(null)
  const [failed, setFailed] = useState(false)
  const [showMore, setShowMore] = useState(false)
  const [applying, setApplying] = useState(false)
  const [buildJobId, setBuildJobId] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    setFailed(false)
    getRecommendation(documentId)
      .then((data) => !cancelled && setRec(data))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [documentId, enrichmentStatus, nonce])

  async function makeDefault(target: Recommendation) {
    // Remember what was in use, so the improvement can be measured against it afterwards.
    if (target.current_default !== target.recommended) writePrevious(documentId, target.current_default)
    await setDefaultStrategy(target.recommended)
    toast.success(`Now using ${target.display_name} for this workspace`)
    setNonce((n) => n + 1)
    onApplied()
  }

  const build = useJob(buildJobId, (job) => {
    setBuildJobId(null)
    if (job.status !== 'done') {
      toast.error(job.error ?? 'Could not build what this strategy needs')
      setApplying(false)
      return
    }
    if (rec) void makeDefault(rec).finally(() => setApplying(false))
  })

  async function apply() {
    if (!rec) return
    setApplying(true)
    try {
      if (!rec.available && rec.action) {
        setBuildJobId((await prepareStrategy(rec.recommended, documentId)).job_id)
        return // continues in the job's completion handler
      }
      await makeDefault(rec)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not switch strategy')
    }
    setApplying(false)
  }

  if (failed) return null
  if (!rec) {
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface-raised p-4" role="status" aria-label="Analysing the document">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    )
  }

  const inUse = rec.current_default === rec.recommended
  // Before switching: what you use now. After: what you used before (or plain hybrid search
  // if this strategy was already the default when the document arrived).
  const baseline = inUse ? (readPrevious(documentId) ?? (rec.recommended === 'hybrid' ? 'naive' : 'hybrid')) : rec.current_default
  const label = (id: string) => (id === rec.recommended ? rec.display_name : (nameOf?.(id) ?? id.replace(/_/g, ' ')))
  return (
    <section
      className="lacquer-card flex flex-col gap-3 rounded-xl border border-gold/40 bg-surface-raised p-4"
      data-testid="recommendation-card"
      data-recommended={rec.recommended}
      aria-label="Strategy recommendation"
    >
      <div className="flex items-start gap-2">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-gold" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] tracking-wide text-muted-foreground uppercase">For this document we recommend</p>
          <p className="font-display text-lg leading-tight font-semibold text-foreground" data-testid="recommended-strategy">{rec.display_name}</p>
        </div>
        <Badge variant="outline" title="How clearly the document's measurements separate this strategy from the next best. Not a probability of being right.">
          {Math.round(rec.confidence * 100)}% confidence
        </Badge>
      </div>

      <ul className="flex flex-col gap-1.5 text-xs text-foreground" data-testid="recommendation-reasons">
        {rec.reasons.map((reason) => (
          <li key={reason} className="flex gap-2">
            <Check className="mt-0.5 size-3 shrink-0 text-success" aria-hidden="true" />
            <span>{reason}</span>
          </li>
        ))}
      </ul>

      {rec.provisional && <p className="text-[11px] text-warning">The knowledge graph is still being built; this may change when it finishes.</p>}
      {!rec.available && !build.active && <p className="text-[11px] text-warning">{rec.unavailable_reason} {rec.action ? '“Use this strategy” will build it first.' : ''}</p>}

      {build.active && (
        <div className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          <ProgressBar value={build.progress} label="Preparing the strategy" tone="live" />
          <span>{build.message}</span>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {inUse ? (
          <Badge variant="success" data-testid="recommendation-in-use">in use — this is your default</Badge>
        ) : (
          <Button size="sm" onClick={() => void apply()} disabled={applying || (!rec.available && !rec.action)} data-testid="use-recommended">
            {applying ? 'Switching…' : 'Use this strategy'}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => onCompare(inUse && rec.runner_up ? [rec.runner_up] : [rec.recommended])} data-testid="compare-recommended">
          <GitCompareArrows className="size-3.5" /> Compare
        </Button>
        <button type="button" className="ml-auto text-[11px] text-muted-foreground underline-offset-2 hover:underline" aria-expanded={showMore} onClick={() => setShowMore((v) => !v)}>
          {showMore ? 'Hide details' : 'How was this decided?'}
        </button>
      </div>

      {inUse && <ImprovementPanel documentId={documentId} baseline={baseline} recommended={rec.recommended} nameOf={label} />}

      {showMore && (
        <div className="flex flex-col gap-3 border-t border-border pt-3 text-[11px]" data-testid="recommendation-details">
          <p className="text-muted-foreground">
            Decided by fixed rules over measurements of this document — no model was asked for an opinion.
            {rec.runner_up_display_name && <> Runner-up: <span className="text-foreground">{rec.runner_up_display_name}</span>.</>}
          </p>
          {rec.not_recommended.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-foreground">Not recommended here</p>
              <ul className="flex flex-col gap-1 text-muted-foreground">
                {rec.not_recommended.map((item) => (
                  <li key={item.id}><span className="text-foreground">{item.id.replace(/_/g, ' ')}</span> — {item.why}</li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <p className="mb-1 font-medium text-foreground">Rules checked</p>
            <ul className="flex flex-col gap-0.5">
              {rec.rule_trace.map((rule) => (
                <li key={rule.rule} className={cn('flex gap-1.5', rule.fired ? 'text-foreground' : 'text-muted-foreground/70')}>
                  <span aria-hidden="true">{rule.fired ? '●' : '○'}</span>
                  <span>{rule.description}{rule.fired ? ' — applied' : ''}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  )
}
