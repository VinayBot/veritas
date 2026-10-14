import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, GitCompareArrows, RefreshCw, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ProgressBar } from '@/components/ui/progress-bar'
import { Skeleton } from '@/components/ui/skeleton'
import { useJob } from '@/hooks/useJob'
import { MEASURED_EVENT, announceMeasured, getRecommendation, prepareStrategy, setDocumentStrategy, startMeasure } from '@/lib/api/client'
import type { Recommendation } from '@/lib/api/types'
import { cn } from '@/lib/utils'

const MEASURING: Recommendation['measure_status'][] = ['queued', 'running']
const FINISHED: Recommendation['measure_status'][] = ['done', 'skipped', 'failed']

/**
 * The strategy this document is answered with, and why. After upload the app measures the
 * main strategies on a few questions from the document and picks the highest scorer; the
 * card shows that ranking with its scores. Before the measurement it shows the rules'
 * prediction, clearly marked as not measured. Compare is there for a closer look.
 */
export function RecommendationCard({
  documentId,
  enrichmentStatus,
  onApplied,
  onCompare,
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
  const [measureJobId, setMeasureJobId] = useState<string | null>(null)
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

  // A comparison or evaluation finishing anywhere can change what is measured best.
  useEffect(() => {
    const refresh = () => setNonce((n) => n + 1)
    window.addEventListener(MEASURED_EVENT, refresh)
    return () => window.removeEventListener(MEASURED_EVENT, refresh)
  }, [])

  // While the automatic measurement runs, look again every few seconds.
  const measuring = rec !== null && MEASURING.includes(rec.measure_status)
  // Also keep looking while a measurement is due but not queued yet: it starts once the
  // background graph pass finishes, possibly a moment after this card last asked.
  const awaiting = rec !== null && rec.auto_measure && rec.basis !== 'measured' && !FINISHED.includes(rec.measure_status)
  useEffect(() => {
    if (!measuring && !awaiting) return
    const timer = window.setInterval(() => setNonce((n) => n + 1), 5000)
    return () => window.clearInterval(timer)
  }, [measuring, awaiting])
  const [wasMeasuring, setWasMeasuring] = useState(false)
  useEffect(() => {
    if (measuring) setWasMeasuring(true)
    else if (wasMeasuring && rec?.measure_status === 'done') {
      setWasMeasuring(false)
      announceMeasured()
      onApplied()
      toast.success(`Measured: ${rec.display_name} scored best and now answers this document`)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reacts to the status change only
  }, [measuring, rec?.measure_status])

  async function adoptForDocument(target: Recommendation) {
    await setDocumentStrategy(documentId, target.recommended)
    toast.success(`${target.display_name} now answers this document`)
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
    if (rec) void adoptForDocument(rec).finally(() => setApplying(false))
  })

  const measureJob = useJob(measureJobId, (job) => {
    setMeasureJobId(null)
    if (job.status === 'failed') toast.error(job.error ?? 'The measurement failed')
    announceMeasured()
    setNonce((n) => n + 1)
    onApplied()
  })

  async function apply() {
    if (!rec) return
    setApplying(true)
    try {
      if (!rec.available && rec.action) {
        setBuildJobId((await prepareStrategy(rec.recommended, documentId)).job_id)
        return // continues in the job's completion handler
      }
      await adoptForDocument(rec)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not switch strategy')
    }
    setApplying(false)
  }

  async function measureNow() {
    try {
      setMeasureJobId((await startMeasure(documentId)).job_id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not start the measurement')
    }
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

  const measuredBasis = rec.basis === 'measured' && rec.measured !== null
  const inUse = rec.current_default === rec.recommended
  const autoSelected = inUse && rec.strategy_source === 'measured'
  const top = rec.measured?.ranking.find((e) => e.strategy === rec.recommended)
  const busy = measuring || measureJob.active
  const others = (rec.measured?.ranking ?? []).filter((e) => e.strategy !== rec.recommended).map((e) => e.strategy)

  return (
    <section
      className="lacquer-card flex flex-col gap-3 rounded-xl border border-gold/40 bg-surface-raised p-4"
      data-testid="recommendation-card"
      data-recommended={rec.recommended}
      data-basis={rec.basis}
      aria-label="Strategy recommendation"
    >
      <div className="flex items-start gap-2">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-gold" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] tracking-wide text-muted-foreground uppercase">
            {measuredBasis ? 'Best for this document · measured' : 'Suggested for this document'}
          </p>
          <p className="flex items-baseline gap-2 font-display text-lg leading-tight font-semibold text-foreground">
            <span data-testid="recommended-strategy">{rec.display_name}</span>
            {top && (
              <span className="text-sm font-medium text-success tabular-nums" data-testid="recommended-score" title="Combined quality score from 0 to 1">
                score {top.score.toFixed(2)}
              </span>
            )}
          </p>
        </div>
        <Badge
          variant={measuredBasis ? 'success' : 'outline'}
          data-testid="recommendation-basis"
          title={
            measuredBasis
              ? 'Chosen from strategies actually answering questions with known answers from this document.'
              : 'Predicted from the shape of the document (its entities, tables, length). Not yet checked by measurement.'
          }
        >
          {measuredBasis ? `${rec.measured!.n} questions` : 'not measured yet'}
        </Badge>
      </div>

      {busy && (
        <div className="flex flex-col gap-1.5 text-[11px] text-muted-foreground" data-testid="measuring">
          <ProgressBar value={measureJob.active ? measureJob.progress : undefined} label="Measuring strategies" tone="live" />
          <span>
            Measuring strategies on 5 questions from this document to pick the best — usually one to two minutes. Your questions are answered first
            meanwhile.
          </span>
        </div>
      )}

      {rec.measured && (
        <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-surface p-3" data-testid="measured-ranking">
          <p className="text-[11px] text-muted-foreground">
            Quality score on {rec.measured.n} question{rec.measured.n === 1 ? '' : 's'} from this document (faithfulness, relevance, correctness and
            ranking combined, 0–1){rec.measured.small_sample ? ' · small sample' : ''}
          </p>
          {rec.measured.ranking.map((entry) => (
            <div key={entry.strategy} className="flex items-center gap-2 text-xs" data-testid={`ranking-${entry.strategy}`}>
              <span className={cn('w-28 shrink-0 truncate', entry.strategy === rec.recommended ? 'font-medium text-foreground' : 'text-muted-foreground')}>
                {entry.display_name}
              </span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-pill bg-surface-raised" aria-hidden="true">
                <span
                  className={cn('block h-full origin-left rounded-pill transition-transform duration-large ease-enter', entry.strategy === rec.recommended ? 'bg-success' : 'bg-muted-foreground/50')}
                  style={{ transform: `scaleX(${Math.max(0.02, entry.score)})` }}
                />
              </span>
              <span className="w-9 text-right tabular-nums text-foreground">{entry.score.toFixed(2)}</span>
            </div>
          ))}
          {!measuredBasis && (
            <p className="text-[11px] text-warning" data-testid="unmeasured-pick">
              {rec.display_name} has not been measured on this document yet.
            </p>
          )}
        </div>
      )}

      {!rec.measured && !busy && (
        <ul className="flex flex-col gap-1.5 text-xs text-foreground" data-testid="recommendation-reasons">
          {rec.reasons.map((reason) => (
            <li key={reason} className="flex gap-2">
              <Check className="mt-0.5 size-3 shrink-0 text-success" aria-hidden="true" />
              <span>{reason}</span>
            </li>
          ))}
        </ul>
      )}

      {rec.provisional && <p className="text-[11px] text-warning">The knowledge graph is still being built; this may change when it finishes.</p>}
      {rec.measure_status === 'failed' && rec.measure_error && <p className="text-[11px] text-warning">The automatic measurement did not finish: {rec.measure_error}</p>}
      {!rec.available && !build.active && <p className="text-[11px] text-warning">{rec.unavailable_reason} {rec.action ? '“Use this strategy” will build it first.' : ''}</p>}

      {build.active && (
        <div className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          <ProgressBar value={build.progress} label="Preparing the strategy" tone="live" />
          <span>{build.message}</span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {inUse ? (
          <Badge variant="success" data-testid="recommendation-in-use">
            {autoSelected ? 'selected automatically · in use' : 'in use for this document'}
          </Badge>
        ) : (
          <Button size="sm" onClick={() => void apply()} disabled={applying || (!rec.available && !rec.action)} data-testid="use-recommended">
            {applying ? 'Switching…' : 'Use this strategy'}
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={() => onCompare(others.length > 0 ? [rec.recommended, ...others].slice(0, 3) : [rec.recommended])}
          data-testid="compare-recommended"
          title="See every strategy's answers and scores side by side, question by question."
        >
          <GitCompareArrows className="size-3.5" /> Compare for details
        </Button>
        {!busy && (
          <Button size="sm" variant="ghost" onClick={() => void measureNow()} data-testid="measure-now" title="Run the measurement again on this document.">
            <RefreshCw className="size-3.5" /> {rec.measured ? 'Re-measure' : 'Measure now'}
          </Button>
        )}
      </div>

      <button
        type="button"
        className="self-end text-[11px] text-muted-foreground underline-offset-2 hover:underline"
        aria-expanded={showMore}
        onClick={() => setShowMore((v) => !v)}
      >
        {showMore ? 'Hide details' : 'How was this decided?'}
      </button>

      {showMore && (
        <div className="flex flex-col gap-3 border-t border-border pt-3 text-[11px]" data-testid="recommendation-details">
          {rec.measured && (
            <ul className="flex flex-col gap-1 text-foreground">
              {rec.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {measuredBasis && rec.rule_recommended !== rec.recommended && (
            <p className="text-muted-foreground" data-testid="rule-overridden">
              From the document's shape alone, the rules suggested <span className="text-foreground">{rec.rule_display_name}</span> (
              {rec.rule_reasons.join('; ')}). Measurement on this document overruled that.
            </p>
          )}
          <p className="text-muted-foreground">
            Before anything is measured, the suggestion comes from fixed rules over the document's shape — no model is asked for an opinion. Once
            strategies have been run on its questions, the highest score wins. Confidence {Math.round(rec.confidence * 100)}% (how far the best is
            ahead of the next).
          </p>
          {rec.not_recommended.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-foreground">Not suggested here</p>
              <ul className="flex flex-col gap-1 text-muted-foreground">
                {rec.not_recommended.map((item) => (
                  <li key={item.id}>
                    <span className="text-foreground">{item.id.replace(/_/g, ' ')}</span> — {item.why}
                  </li>
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
                  <span>
                    {rule.description}
                    {rule.fired ? ' — applied' : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  )
}
