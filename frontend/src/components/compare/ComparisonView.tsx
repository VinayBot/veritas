import { useState } from 'react'
import { toast } from 'sonner'
import { Trophy } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MetricTip } from '@/components/ui/metric-tip'
import { setDocumentStrategy } from '@/lib/api/client'
import type { ComparisonResult, ConfigResultOut, MetricDelta } from '@/lib/api/types'
import { diffWords } from '@/lib/diff'
import type { GlossaryTerm } from '@/lib/glossary'
import { compact, ms, score } from '@/lib/format'
import { cn } from '@/lib/utils'

const METRICS: { key: string; label: string; term: GlossaryTerm; get: (r: ConfigResultOut) => number | null | undefined }[] = [
  { key: 'faithfulness', label: 'Faithfulness', term: 'faithfulness', get: (r) => r.faithfulness },
  { key: 'answer_relevancy', label: 'Answer relevance', term: 'relevancy', get: (r) => r.answer_relevancy },
  { key: 'correctness', label: 'Correctness', term: 'correctness', get: (r) => r.correctness },
  { key: 'precision_at_5', label: 'Context precision@5', term: 'precision', get: (r) => r.retrieval_metrics.precision_at_5 },
  { key: 'recall_at_5', label: 'Context recall@5', term: 'recall', get: (r) => r.retrieval_metrics.recall_at_5 },
]

function tokens(r: ConfigResultOut): number | null {
  return r.avg_prompt_tokens === null || r.avg_completion_tokens === null ? null : r.avg_prompt_tokens + r.avg_completion_tokens
}

function DeltaChip({ delta, lowerIsBetter, format }: { delta: MetricDelta | undefined; lowerIsBetter?: boolean; format: (d: MetricDelta) => string }) {
  if (!delta) return null
  if (Math.abs(delta.delta) < 1e-9) return <span className="text-[10px] text-muted-foreground">no change</span>
  const good = lowerIsBetter ? delta.delta < 0 : delta.delta > 0
  return (
    <span
      className={cn('text-[10px] font-medium tabular-nums', good ? 'text-success' : 'text-danger')}
      title={`Measured over n = ${delta.n}${delta.small_sample ? ' (indicative, small sample)' : ''}`}
    >
      {format(delta)}
    </span>
  )
}

/** Side-by-side strategy columns from one measured comparison: metric bars, latency, tokens,
 * the answers each produced with their differences marked, and a winner only when the
 * measurements support one. */
export function ComparisonView({
  result,
  names,
  onAdopted,
}: {
  result: ComparisonResult
  /** Strategy id -> display name. */
  names: Record<string, string>
  onAdopted?: (strategy: string) => void
}) {
  const [question, setQuestion] = useState(0)
  const [adopting, setAdopting] = useState(false)
  const baseline = result.strategies.find((s) => s.name === result.baseline)
  const label = (id: string) => names[id] ?? id
  const questions = baseline?.samples ?? result.strategies.find((s) => s.samples.length > 0)?.samples ?? []
  const current = questions[question]

  async function adopt(id: string) {
    setAdopting(true)
    try {
      await setDocumentStrategy(result.document_id, id)
      toast.success(`${label(id)} now answers this document`)
      onAdopted?.(id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not change the strategy')
    } finally {
      setAdopting(false)
    }
  }

  return (
    <div className="flex flex-col gap-5" data-testid="comparison-view">
      {result.winner ? (
        <div
          className={cn(
            'flex flex-wrap items-center gap-3 rounded-xl border p-4',
            result.winner.is_baseline ? 'border-border bg-surface-raised' : 'border-gold/50 bg-gold/10',
          )}
          data-testid="winner-banner"
          data-winner={result.winner.id}
        >
          <Trophy className={cn('size-5 shrink-0', result.winner.is_baseline ? 'text-muted-foreground' : 'text-gold')} aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="font-display text-sm font-semibold text-foreground">
              {result.winner.is_baseline ? `Keep ${label(result.baseline)}` : `${label(result.winner.id)} did better`}
            </p>
            <p className="text-xs text-muted-foreground">{result.winner.reason}</p>
          </div>
          {!result.winner.is_baseline && (
            <Button size="sm" disabled={adopting} onClick={() => void adopt(result.winner!.id)} data-testid="adopt-winner">
              Adopt as default
            </Button>
          )}
        </div>
      ) : (
        <p className="rounded-xl border border-border bg-surface-raised p-4 text-xs text-muted-foreground" data-testid="winner-banner" data-winner="">
          No winner is declared: these strategies have no quality metric that all of them measured.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline">n = {result.n_queries} question{result.n_queries === 1 ? '' : 's'}</Badge>
        {result.small_sample && <Badge variant="warning" data-testid="small-sample">indicative, small sample</Badge>}
        {result.dataset && <Badge variant="outline">eval set v{result.dataset.version}</Badge>}
        <span>judge: {result.run_config.judge?.replace('ollama/', '')}</span>
        <span>
          {result.ran.length === 0 ? 'served entirely from cached results — nothing was re-run' : `${result.ran.length} strateg${result.ran.length === 1 ? 'y' : 'ies'} run now`}
        </span>
      </div>

      <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(result.strategies.length, 4)}, minmax(0, 1fr))` }}>
        {result.strategies.map((s) => {
          const deltas = result.deltas[s.name] ?? {}
          const isBase = s.name === result.baseline
          return (
            <article
              key={s.name}
              className={cn('flex flex-col gap-3 rounded-xl border bg-surface p-4', result.winner?.id === s.name && !isBase ? 'border-gold/60' : 'border-border')}
              data-testid={`comparison-column-${s.name}`}
            >
              <header className="flex flex-wrap items-center gap-1.5">
                <h4 className="font-display text-sm font-semibold text-foreground">{label(s.name)}</h4>
                {isBase && <Badge variant="outline">baseline</Badge>}
                {s.cached && <Badge variant="outline" title="This result was measured earlier on the same document, eval set and models.">cached</Badge>}
              </header>
              {s.skipped_reason ? (
                <p className="text-xs text-warning">Did not run: {s.skipped_reason}</p>
              ) : (
                <>
                  <dl className="flex flex-col gap-2">
                    {METRICS.map((m) => {
                      const value = m.get(s)
                      return (
                        <div key={m.key}>
                          <dt className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                            <MetricTip term={m.term}>{m.label}</MetricTip>
                            <span className="flex items-center gap-2">
                              {!isBase && <DeltaChip delta={deltas[m.key]} format={(d) => `${(d.points ?? 0) > 0 ? '+' : ''}${d.points} pts`} />}
                              <span className="font-medium tabular-nums text-foreground">{value === null || value === undefined ? 'not measured' : score(value)}</span>
                            </span>
                          </dt>
                          <dd className="mt-1 h-1.5 overflow-hidden rounded-pill bg-surface-raised">
                            {value !== null && value !== undefined && (
                              <span className="block h-full origin-left rounded-pill bg-accent" style={{ transform: `scaleX(${Math.max(0, Math.min(1, value))})` }} />
                            )}
                          </dd>
                        </div>
                      )
                    })}
                  </dl>
                  <dl className="grid grid-cols-2 gap-2 border-t border-border pt-3 text-[11px]">
                    <div>
                      <dt className="text-muted-foreground"><MetricTip term="p50">Latency p50</MetricTip></dt>
                      <dd className="flex items-baseline gap-1.5">
                        <span className="font-display text-base font-semibold tabular-nums text-foreground">{ms(s.p50_latency_ms)}</span>
                        {!isBase && <DeltaChip delta={deltas.p50_latency_ms} lowerIsBetter format={(d) => `${d.delta > 0 ? '+' : ''}${(d.delta / 1000).toFixed(1)}s`} />}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground"><MetricTip term="tokens">Tokens / question</MetricTip></dt>
                      <dd className="flex items-baseline gap-1.5">
                        <span className="font-display text-base font-semibold tabular-nums text-foreground">{compact(tokens(s)) ?? 'n/m'}</span>
                        {!isBase && <DeltaChip delta={deltas.tokens_per_question} lowerIsBetter format={(d) => `${d.delta > 0 ? '+' : ''}${Math.round(d.delta)}`} />}
                      </dd>
                    </div>
                  </dl>
                </>
              )}
            </article>
          )
        })}
      </div>

      {questions.length > 0 && (
        <section className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-display text-sm font-semibold text-foreground">What each one actually answered</h4>
            {questions.length > 1 && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Button size="xs" variant="outline" disabled={question === 0} onClick={() => setQuestion((q) => q - 1)}>Previous</Button>
                <span className="tabular-nums">{question + 1} / {questions.length}</span>
                <Button size="xs" variant="outline" disabled={question >= questions.length - 1} onClick={() => setQuestion((q) => q + 1)}>Next</Button>
              </div>
            )}
          </div>
          {current && (
            <>
              <p className="text-xs text-foreground"><span className="text-muted-foreground">Q:</span> {current.question}</p>
              {current.reference_answer && <p className="text-xs text-muted-foreground">Reference: {current.reference_answer}</p>}
              <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(result.strategies.length, 4)}, minmax(0, 1fr))` }}>
                {result.strategies.map((s) => {
                  const sample = s.samples.find((x) => x.item_id === current.item_id)
                  const base = baseline?.samples.find((x) => x.item_id === current.item_id)
                  const isBase = s.name === result.baseline
                  return (
                    <div key={s.name} className="rounded-xl border border-border bg-surface p-3 text-xs" data-testid={`comparison-answer-${s.name}`}>
                      <p className="mb-1.5 font-medium text-foreground">{label(s.name)}</p>
                      {!sample ? (
                        <p className="text-muted-foreground">{s.skipped_reason ? 'Did not run.' : 'Not asked this question (agent strategies answer the first 5).'}</p>
                      ) : isBase || !base ? (
                        <p className="leading-relaxed whitespace-pre-wrap text-foreground">{sample.answer}</p>
                      ) : (
                        <p className="leading-relaxed whitespace-pre-wrap text-foreground">
                          {diffWords(base.answer, sample.answer)
                            .filter((part) => part.kind !== 'removed')
                            .map((part, i) =>
                              part.kind === 'added' ? (
                                <mark key={i} className="rounded-sm bg-gold/25 text-foreground" title="Differs from the baseline answer">{part.text}</mark>
                              ) : (
                                <span key={i}>{part.text}</span>
                              ),
                            )}
                        </p>
                      )}
                      {sample && <p className="mt-2 tabular-nums text-muted-foreground">{ms(sample.latency_ms)} · {sample.citations} citation{sample.citations === 1 ? '' : 's'}</p>}
                    </div>
                  )
                })}
              </div>
              <p className="text-[11px] text-muted-foreground">Highlighted text is where an answer differs from the baseline’s.</p>
            </>
          )}
        </section>
      )}
    </div>
  )
}
