import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { motion, useReducedMotion } from 'framer-motion'
import { ArrowRight, TrendingUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ProgressBar } from '@/components/ui/progress-bar'
import { MetricTip } from '@/components/ui/metric-tip'
import { useJob } from '@/hooks/useJob'
import { ApiError, generateDataset, getComparison, listComparisons, listDatasets, startComparison } from '@/lib/api/client'
import type { ComparisonResult, MetricDelta } from '@/lib/api/types'
import type { GlossaryTerm } from '@/lib/glossary'
import { dateTime, ms } from '@/lib/format'
import { DURATION, EASE_ENTER, staggerDelay } from '@/lib/motion'
import { cn } from '@/lib/utils'

const ROWS: { key: string; label: string; term: GlossaryTerm; higherIsBetter: boolean; format: (v: number) => string }[] = [
  { key: 'faithfulness', label: 'Faithfulness', term: 'faithfulness', higherIsBetter: true, format: (v) => v.toFixed(2) },
  { key: 'answer_relevancy', label: 'Answer relevance', term: 'relevancy', higherIsBetter: true, format: (v) => v.toFixed(2) },
  { key: 'correctness', label: 'Correctness', term: 'correctness', higherIsBetter: true, format: (v) => v.toFixed(2) },
  { key: 'recall_at_5', label: 'Context recall@5', term: 'recall', higherIsBetter: true, format: (v) => v.toFixed(2) },
  { key: 'p50_latency_ms', label: 'Median answer time', term: 'p50', higherIsBetter: false, format: (v) => ms(v) ?? '—' },
]

/**
 * What switching to the recommended strategy actually changed for this document: both
 * strategies answer the same eval-set questions and the measured differences are shown side
 * by side. Nothing appears until that run has really happened.
 */
export function ImprovementPanel({
  documentId,
  baseline,
  recommended,
  nameOf,
}: {
  documentId: string
  /** The strategy that was in use before; what the recommendation is measured against. */
  baseline: string
  recommended: string
  nameOf: (id: string) => string
}) {
  const reduced = useReducedMotion()
  const [result, setResult] = useState<{ data: ComparisonResult; at: string } | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [preparing, setPreparing] = useState(false)

  // A measurement made earlier for this exact pair is shown again rather than re-run.
  useEffect(() => {
    let cancelled = false
    setResult(null)
    listComparisons(documentId)
      .then(({ comparisons }) => {
        const match = comparisons.find((c) => c.result.dataset !== null && c.result.baseline === baseline && recommended in c.result.deltas)
        if (match && !cancelled) setResult({ data: match.result, at: match.created_at })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [documentId, baseline, recommended])

  const job = useJob(jobId, (finished) => {
    setJobId(null)
    const id = finished.result?.comparison_id
    if (finished.status !== 'done' || typeof id !== 'string') {
      if (finished.status === 'failed') toast.error(finished.error ?? 'The measurement failed')
      return
    }
    getComparison(id)
      .then((c) => setResult({ data: c.result, at: c.created_at }))
      .catch(() => toast.error('The measurement finished but its result could not be loaded'))
  })

  const measure = useCallback(async () => {
    setPreparing(true)
    try {
      const { datasets } = await listDatasets(documentId)
      const datasetId = datasets[0]?.id ?? (await generateDataset(documentId, 8)).dataset_id
      setJobId((await startComparison({ document_id: documentId, strategies: [baseline, recommended], dataset_id: datasetId, baseline })).job_id)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not start the measurement')
    } finally {
      setPreparing(false)
    }
  }, [documentId, baseline, recommended])

  if (baseline === recommended) return null
  const deltas: Record<string, MetricDelta> = result?.data.deltas[recommended] ?? {}
  const rows = ROWS.filter((r) => deltas[r.key])

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-3" data-testid="improvement-panel">
      <div className="flex items-center gap-2 text-xs font-medium text-foreground">
        <TrendingUp className="size-3.5 text-success" aria-hidden="true" />
        {nameOf(baseline)} <ArrowRight className="size-3 text-muted-foreground" aria-hidden="true" /> {nameOf(recommended)}
      </div>

      {job.active || preparing ? (
        <div className="flex flex-col gap-1.5 text-[11px] text-muted-foreground" data-testid="improvement-progress">
          <ProgressBar value={preparing ? undefined : job.progress} label="Measuring the improvement" tone="live" />
          <span className="flex items-center justify-between gap-2">
            <span className="truncate">{preparing ? 'Preparing questions with known answers…' : (job.message ?? 'Working…')}</span>
            {!preparing && (
              <button type="button" className="underline-offset-2 hover:underline" onClick={job.cancel}>
                Cancel
              </button>
            )}
          </span>
        </div>
      ) : result && rows.length > 0 ? (
        <>
          <ul className="flex flex-col gap-2" data-testid="improvement-results">
            {rows.map((row, i) => {
              const d = deltas[row.key]
              const flat = Math.abs(d.delta) < (row.key === 'p50_latency_ms' ? 50 : 0.005)
              const better = !flat && (row.higherIsBetter ? d.delta > 0 : d.delta < 0)
              const change = row.key === 'p50_latency_ms' ? `${d.delta > 0 ? '+' : '−'}${ms(Math.abs(d.delta))}` : `${d.delta > 0 ? '+' : '−'}${Math.abs(d.delta).toFixed(2)}`
              return (
                <motion.li
                  key={row.key}
                  initial={reduced ? false : { opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: reduced ? 0 : DURATION.standard, ease: EASE_ENTER, delay: reduced ? 0 : staggerDelay(i) }}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <MetricTip term={row.term} className="text-muted-foreground">
                    {row.label}
                  </MetricTip>
                  <span className="flex items-center gap-2 tabular-nums">
                    <span className="text-muted-foreground">{row.format(d.baseline)}</span>
                    <ArrowRight className="size-3 text-muted-foreground" aria-hidden="true" />
                    <span className="text-foreground">{row.format(d.value)}</span>
                    <span className={cn('w-16 rounded-pill px-1.5 py-0.5 text-center text-[11px] font-medium', flat ? 'bg-surface-raised text-muted-foreground' : better ? 'bg-success/15 text-success' : 'bg-danger/15 text-danger')}>
                      {flat ? 'same' : change}
                    </span>
                  </span>
                </motion.li>
              )
            })}
          </ul>
          <p className="text-[11px] text-muted-foreground">
            Measured {dateTime(result.at)} on {result.data.n_queries} questions from eval set v{result.data.dataset?.version ?? '?'}.
            {result.data.small_sample_note ? ` ${result.data.small_sample_note}` : ''}{' '}
            <button type="button" className="underline-offset-2 hover:underline" onClick={() => void measure()}>
              Measure again
            </button>
          </p>
        </>
      ) : (
        <>
          <p className="text-[11px] text-muted-foreground">
            {result ? 'The last measurement produced no comparable numbers.' : 'Not measured yet.'} Both strategies answer the same questions with known answers, and the
            differences in quality and speed are shown here. Takes a few minutes.
          </p>
          <Button size="sm" variant="outline" className="self-start" onClick={() => void measure()} data-testid="measure-improvement">
            <TrendingUp className="size-3.5" /> Measure the improvement
          </Button>
        </>
      )}
    </div>
  )
}
