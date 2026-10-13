import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { ProgressBar } from '@/components/ui/progress-bar'
import { Segmented } from '@/components/ui/segmented'
import { Textarea } from '@/components/ui/textarea'
import { ComparisonView } from './ComparisonView'
import { useJob } from '@/hooks/useJob'
import { estimateComparison, getComparison, listDatasets, startComparison, type CompareParams } from '@/lib/api/client'
import type { CompareEstimate, ComparisonResult, EvalDataset, Strategy } from '@/lib/api/types'
import { cn } from '@/lib/utils'

function duration(seconds: number): string {
  if (seconds < 60) return `about ${Math.max(1, Math.round(seconds))} seconds`
  return `about ${Math.round(seconds / 60)} minute${Math.round(seconds / 60) === 1 ? '' : 's'}`
}

/**
 * Compare strategies on one question or on a saved eval set. Shows what it will cost first
 * (questions x strategies x latency, cached results free), runs only after confirmation, can
 * be cancelled, and then shows measured results.
 */
export function CompareDialog({
  open,
  onOpenChange,
  documentId,
  strategies,
  defaultStrategy,
  initialQuery,
  initialSelected,
  onAdopted,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  documentId: string
  strategies: Strategy[]
  defaultStrategy: string
  initialQuery?: string
  initialSelected?: string[]
  onAdopted?: (strategy: string) => void
}) {
  const [source, setSource] = useState<'query' | 'dataset'>(initialQuery ? 'query' : 'dataset')
  const [query, setQuery] = useState(initialQuery ?? '')
  const [datasets, setDatasets] = useState<EvalDataset[] | null>(null)
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>(initialSelected ?? [])
  const [estimate, setEstimate] = useState<CompareEstimate | null>(null)
  const [estimateError, setEstimateError] = useState<unknown>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [result, setResult] = useState<ComparisonResult | null>(null)

  const names = useMemo(() => Object.fromEntries(strategies.map((s) => [s.id, s.display_name])), [strategies])

  useEffect(() => {
    if (!open) return
    setResult(null)
    setJobId(null)
    setQuery(initialQuery ?? '')
    setSource(initialQuery ? 'query' : 'dataset')
    setSelected(initialSelected ?? strategies.filter((s) => s.available && s.id !== defaultStrategy).slice(0, 1).map((s) => s.id))
    listDatasets(documentId)
      .then((data) => {
        setDatasets(data.datasets)
        setDatasetId(data.datasets[0]?.id ?? null)
      })
      .catch(() => setDatasets([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset once per opening
  }, [open, documentId])

  const params: CompareParams | null = useMemo(() => {
    if (selected.length === 0) return null
    if (source === 'query') return query.trim() ? { document_id: documentId, strategies: selected, query: query.trim() } : null
    return datasetId ? { document_id: documentId, strategies: selected, dataset_id: datasetId } : null
  }, [documentId, selected, source, query, datasetId])

  // The estimate follows the selection, debounced so typing a question does not flood the API.
  useEffect(() => {
    setEstimate(null)
    setEstimateError(null)
    if (!open || !params || result) return
    const timer = window.setTimeout(() => {
      estimateComparison(params).then(setEstimate).catch(setEstimateError)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [open, params, result])

  const job = useJob(jobId, (finished) => {
    if (finished.status === 'done' && finished.result?.comparison_id) {
      getComparison(String(finished.result.comparison_id))
        .then((c) => setResult(c.result))
        .catch((err) => toast.error(err instanceof Error ? err.message : 'Could not load the comparison'))
    } else if (finished.status === 'failed') {
      toast.error(finished.error ?? 'The comparison failed')
    } else if (finished.status === 'cancelled') {
      toast.message('Comparison cancelled')
    }
    setJobId(null)
  })

  async function run() {
    if (!params) return
    try {
      setJobId((await startComparison(params)).job_id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not start the comparison')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-5xl" data-testid="compare-dialog" data-lenis-prevent>
        <DialogHeader>
          <DialogTitle>Compare strategies</DialogTitle>
          <DialogDescription>
            Runs each strategy on the same question(s) against this document and scores them the same way. Differences are measured, with the number of
            questions they rest on.
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <>
            <ComparisonView result={result} names={names} onAdopted={onAdopted} />
            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={() => setResult(null)}>Compare something else</Button>
            </div>
          </>
        ) : job.active ? (
          <div className="flex flex-col gap-3 py-6" data-testid="compare-progress">
            <ProgressBar value={job.progress} label="Comparison progress" tone="live" />
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{job.message ?? 'Starting'} · {Math.round(job.progress * 100)}%</span>
              <Button size="xs" variant="outline" onClick={job.cancel} data-testid="compare-cancel">Cancel</Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <Segmented
                label="What to compare on"
                value={source}
                onChange={setSource}
                options={[
                  { value: 'query', label: 'One question' },
                  { value: 'dataset', label: 'An eval set', disabled: (datasets?.length ?? 0) === 0, title: (datasets?.length ?? 0) === 0 ? 'No eval set exists for this document yet — generate one in Evaluation.' : undefined },
                ]}
              />
              {source === 'query' ? (
                <Textarea value={query} onChange={(e) => setQuery(e.target.value)} placeholder="The question every strategy will answer" aria-label="Question to compare on" className="min-h-16" />
              ) : datasets === null ? (
                <LoadingState shape="lines" rows={1} label="Loading eval sets" />
              ) : (
                <select
                  value={datasetId ?? ''}
                  onChange={(e) => setDatasetId(e.target.value)}
                  aria-label="Eval set"
                  className="h-9 rounded-md border border-border bg-surface px-2.5 text-sm text-foreground"
                >
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      Eval set v{d.version} — {d.item_count} questions
                    </option>
                  ))}
                </select>
              )}
            </div>

            <fieldset>
              <legend className="mb-2 text-xs font-medium text-muted-foreground">
                Compare against <span className="text-foreground">{names[defaultStrategy]}</span> (the current default, always included)
              </legend>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {strategies
                  .filter((s) => s.id !== defaultStrategy)
                  .map((s) => {
                    const on = selected.includes(s.id)
                    return (
                      <label
                        key={s.id}
                        className={cn(
                          'flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-xs',
                          on ? 'border-accent/60 bg-accent/10' : 'border-border',
                          !s.available && 'cursor-not-allowed opacity-50',
                        )}
                        title={s.available ? undefined : (s.unavailable_reason ?? undefined)}
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5 accent-[var(--color-accent)]"
                          checked={on}
                          disabled={!s.available}
                          data-testid={`compare-pick-${s.id}`}
                          onChange={() => setSelected((prev) => (on ? prev.filter((id) => id !== s.id) : [...prev, s.id]))}
                        />
                        <span>
                          <span className="block font-medium text-foreground">{s.display_name}</span>
                          <span className="block text-muted-foreground">{s.available ? s.best_for : s.unavailable_reason}</span>
                        </span>
                      </label>
                    )
                  })}
              </div>
            </fieldset>

            {estimateError ? (
              <ErrorState error={estimateError} compact />
            ) : estimate ? (
              <div className="rounded-xl border border-warning/40 bg-warning/10 p-4 text-xs" data-testid="compare-estimate">
                <p className="font-medium text-foreground">
                  {estimate.all_cached
                    ? 'Already measured — this will open instantly and run nothing.'
                    : `This will take ${duration(estimate.estimated_seconds)} and make about ${estimate.total_llm_calls} model calls.`}
                </p>
                <ul className="mt-2 flex flex-col gap-1 text-muted-foreground">
                  {estimate.strategies.map((row) => (
                    <li key={row.strategy} className="flex flex-wrap justify-between gap-2">
                      <span className="text-foreground">{names[row.strategy] ?? row.strategy}</span>
                      <span>
                        {row.cached ? 'cached — free' : `${row.questions} question${row.questions === 1 ? '' : 's'} × ~${row.latency_per_question_s}s (${row.latency_source}) + scoring`}
                      </span>
                    </li>
                  ))}
                </ul>
                {!estimate.all_cached && (
                  <p className="mt-2 text-muted-foreground">
                    {estimate.concurrency === 1 ? 'Strategies run one after another on this hardware tier.' : `Up to ${estimate.concurrency} strategies run side by side.`}{' '}
                    You can cancel at any time.
                  </p>
                )}
              </div>
            ) : (
              params && <LoadingState shape="lines" rows={2} label="Estimating cost" />
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
              <Button onClick={() => void run()} disabled={!params || !estimate} data-testid="compare-run">
                {estimate?.all_cached ? 'Open comparison' : 'Run comparison'}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
