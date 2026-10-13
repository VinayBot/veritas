import { useState } from 'react'
import { GitCompareArrows } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Collapsible } from '@/components/ui/collapsible'
import { MetricTip } from '@/components/ui/metric-tip'
import type { GlossaryTerm } from '@/lib/glossary'
import type { ReportResponse, RetrievedChunk, StageTiming } from '@/lib/api/types'
import { compact, modelName, ms, parseTime, pct, score } from '@/lib/format'
import { cn } from '@/lib/utils'

const FOUND_BY: Record<string, { label: string; tip: string }> = {
  dense: { label: 'meaning', tip: 'Found by search-by-meaning (dense) only.' },
  sparse: { label: 'keyword', tip: 'Found by keyword search (BM25) only.' },
  both: { label: 'meaning + keyword', tip: 'Found by both rankings, which is why rank fusion scored it highly.' },
  graph: { label: 'graph hop', tip: 'Reached by following a relation in the knowledge graph.' },
  'both+graph': { label: 'meaning + keyword + graph', tip: 'Found by both rankings and by graph traversal.' },
  'dense+graph': { label: 'meaning + graph', tip: 'Found by search-by-meaning and by graph traversal.' },
  'sparse+graph': { label: 'keyword + graph', tip: 'Found by keyword search and by graph traversal.' },
  hybrid: { label: 'hybrid search', tip: 'Found by hybrid search; the individual ranks were not recorded.' },
}

function Metric({ label, term, value, caption }: { label: string; term: GlossaryTerm; value: string | undefined; caption?: string }) {
  return (
    <div className="rounded-lg bg-surface p-2.5">
      <dt className="text-[11px] text-muted-foreground">
        <MetricTip term={term}>{label}</MetricTip>
      </dt>
      <dd className={cn('font-display text-lg leading-tight font-semibold tabular-nums', value ? 'text-foreground' : 'text-sm font-medium text-muted-foreground')}>
        {value ?? 'Not measured'}
      </dd>
      {caption && <dd className="text-[10px] text-muted-foreground">{caption}</dd>}
    </div>
  )
}

function Funnel({ report }: { report: ReportResponse }) {
  const funnel = report.retrieval?.funnel
  if (!funnel) return <p className="text-xs text-muted-foreground">No search was run for this answer (it was served from cache or blocked before retrieval).</p>
  const considered = (funnel.dense_candidates ?? 0) + (funnel.sparse_candidates ?? 0)
  const steps: { label: string; value: number | null; tip: string }[] = [
    { label: 'Considered', value: considered, tip: `Candidates from search-by-meaning (${funnel.dense_candidates ?? 0}) and keyword search (${funnel.sparse_candidates ?? 0}), before merging.` },
    { label: 'After rank fusion', value: funnel.after_fusion, tip: 'Unique chunks after the two rankings were merged.' },
    { label: 'After rerank', value: funnel.after_rerank, tip: 'Chunks re-scored by the reranker. Not measured when the strategy does not rerank.' },
    { label: 'In context', value: funnel.in_context, tip: 'Chunks actually shown to the model.' },
    { label: 'Used in answer', value: funnel.used_in_answer, tip: 'Chunks the answer cites.' },
  ]
  const max = Math.max(1, ...steps.map((s) => s.value ?? 0))
  return (
    <ol className="flex flex-col gap-1.5" data-testid="retrieval-funnel">
      {steps.map((step) => (
        <li key={step.label} className="grid grid-cols-[7.5rem_1fr_2.5rem] items-center gap-2 text-[11px]">
          <MetricTip tip={step.tip} className="text-muted-foreground">{step.label}</MetricTip>
          <span className="h-2 overflow-hidden rounded-pill bg-surface" aria-hidden="true">
            {step.value !== null && <span className="block h-full origin-left rounded-pill bg-accent" style={{ transform: `scaleX(${step.value / max})` }} />}
          </span>
          <span className="text-right tabular-nums text-foreground">{step.value ?? 'n/m'}</span>
        </li>
      ))}
      {funnel.searches > 1 && <li className="text-[10px] text-muted-foreground">Summed across {funnel.searches} searches the agent ran for this answer.</li>}
    </ol>
  )
}

function ChunkRow({
  chunk,
  hovered,
  onHover,
}: {
  chunk: RetrievedChunk
  hovered: boolean
  onHover: (id: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const found = FOUND_BY[chunk.found_by ?? ''] ?? { label: chunk.found_by ?? chunk.source ?? 'unknown', tip: 'How this chunk was found.' }
  return (
    <li
      data-testid={`chunk-${chunk.chunk_id}`}
      data-used={chunk.used}
      data-highlighted={hovered}
      onMouseEnter={() => onHover(chunk.chunk_id)}
      onMouseLeave={() => onHover(null)}
      className={cn(
        'rounded-lg border p-2.5 text-xs transition-colors duration-micro',
        hovered ? 'border-gold bg-gold/10' : chunk.used ? 'border-accent/40 bg-surface' : 'border-border bg-surface opacity-80',
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        {chunk.citation_marker !== null ? (
          <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-sm bg-accent/25 px-1 text-[10px] font-semibold text-foreground">{chunk.citation_marker}</span>
        ) : (
          <span className="text-[10px] text-muted-foreground" title="Shown to the model but not cited in the answer.">not cited</span>
        )}
        <MetricTip tip={found.tip} className="rounded-pill bg-surface-raised px-1.5 py-0.5 text-[10px] text-foreground">{found.label}</MetricTip>
        {chunk.flagged_injection && <Badge variant="warning" title="The retrieval guardrail flagged this text as a possible prompt injection.">flagged</Badge>}
        <span className="ml-auto tabular-nums text-muted-foreground" title={chunk.rerank_score !== null ? 'Reranker score (higher is more relevant; can be negative).' : 'Fusion or similarity score.'}>
          {chunk.score !== null ? chunk.score.toFixed(3) : 'no score'}
        </span>
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground">
        {chunk.section_path ? `§ ${chunk.section_path}` : 'section not recorded'} · page {chunk.page ?? 'not recorded'}
        {chunk.dense_rank !== null && ` · meaning rank ${chunk.dense_rank}`}
        {chunk.sparse_rank !== null && ` · keyword rank ${chunk.sparse_rank}`}
      </p>
      <button type="button" className="mt-1 block w-full text-left text-foreground" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className={cn('block whitespace-pre-wrap', !open && 'line-clamp-2')}>{chunk.text}</span>
      </button>
    </li>
  )
}

function Timeline({ timings, total }: { timings: StageTiming[]; total: number | null }) {
  const [selected, setSelected] = useState<number | null>(null)
  if (timings.length === 0) return <p className="text-xs text-muted-foreground">Stage timings were not recorded for this answer.</p>
  const start = Math.min(...timings.map((t) => parseTime(t.started_at).getTime()))
  const end = Math.max(...timings.map((t) => parseTime(t.started_at).getTime() + (t.duration_ms ?? 0)))
  const span = Math.max(1, end - start)
  const picked = selected !== null ? timings[selected] : null
  return (
    <div className="flex flex-col gap-2" data-testid="trace-timeline">
      <ol className="flex flex-col gap-1">
        {timings.map((t, i) => {
          const offset = (parseTime(t.started_at).getTime() - start) / span
          const width = Math.max(0.012, (t.duration_ms ?? 0) / span)
          return (
            <li key={`${t.stage}-${i}`}>
              <button
                type="button"
                onClick={() => setSelected(selected === i ? null : i)}
                aria-expanded={selected === i}
                data-testid={`timeline-stage-${t.stage}`}
                className={cn('grid w-full grid-cols-[6.5rem_1fr_3.5rem] items-center gap-2 rounded-md px-1 py-0.5 text-left text-[11px] transition-colors duration-micro hover:bg-surface', selected === i && 'bg-surface')}
              >
                <span className="truncate text-foreground">{t.stage.replace(/_/g, ' ')}</span>
                <span className="relative h-2.5 rounded-pill bg-surface" aria-hidden="true">
                  <span
                    className={cn('absolute inset-y-0 rounded-pill', t.status === 'error' ? 'bg-danger' : t.status === 'blocked' ? 'bg-warning' : 'bg-live')}
                    style={{ left: `${offset * 100}%`, width: `${Math.min(width, 1 - offset) * 100}%` }}
                  />
                </span>
                <span className="text-right tabular-nums text-muted-foreground">{ms(t.duration_ms)}</span>
              </button>
            </li>
          )
        })}
      </ol>
      <p className="text-[10px] text-muted-foreground">
        Bars are positioned by each stage’s real start time and measured duration{total !== null ? `; the whole answer took ${ms(total)}` : ''}. Select a stage to see what went in and out.
      </p>
      {picked && (
        <div className="rounded-lg border border-border bg-surface p-2.5 text-[11px]" data-testid="timeline-detail">
          <p className="mb-1 font-medium text-foreground">{picked.stage.replace(/_/g, ' ')} · {picked.status} · {ms(picked.duration_ms)}</p>
          <p className="text-muted-foreground">In: <span className="text-foreground">{picked.input_preview ?? 'not recorded for this stage'}</span></p>
          <p className="mt-1 text-muted-foreground">Out: <span className="text-foreground">{picked.output_preview ?? 'not recorded for this stage'}</span></p>
          {Object.keys(picked.metrics).length > 0 && (
            <pre className="mt-1.5 overflow-x-auto rounded-md bg-surface-raised p-2 font-mono text-[10px] text-foreground">{JSON.stringify(picked.metrics, null, 1)}</pre>
          )}
        </div>
      )}
    </div>
  )
}

/** Everything about one answer: what produced it, how well it is supported, what was
 * retrieved and why, and where the time went. Every value is read from the saved report. */
export function AnalysisPanel({
  report,
  strategyName,
  hoveredChunk,
  onHoverChunk,
  onCompare,
}: {
  report: ReportResponse
  strategyName: string
  hoveredChunk: string | null
  onHoverChunk: (id: string | null) => void
  onCompare: () => void
}) {
  const quality = report.quality
  const grounding = quality.grounding
  const usage = report.usage
  const chunks = report.retrieval?.chunks ?? []
  const tokenTotal = usage && usage.llm_calls > 0 && !usage.calls_without_usage ? usage.prompt_tokens + usage.completion_tokens : null
  const unsupported = grounding?.sentences.filter((s) => !s.supported) ?? []

  return (
    <div className="flex flex-col gap-3" data-testid="analysis-panel" data-report={report.id}>
      <Collapsible id="answer-strategy" title="How it was answered" summary={ms(report.latency_ms)}>
        <div className="flex flex-col gap-3 text-xs">
          <p className="text-foreground">
            Answered with: <span className="font-semibold" data-testid="answered-with">{strategyName}</span>
            <span className="text-muted-foreground"> · {report.detail === 'deep' ? 'deep answer (7–8 lines)' : 'quick answer (3–4 lines)'}</span>
            {report.cache_hit && <Badge variant="outline" className="ml-1.5" title="A near-identical earlier question was answered from the semantic cache.">from cache</Badge>}
          </p>
          <dl className="grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-surface p-2.5">
              <dt className="text-[11px] text-muted-foreground">Generator</dt>
              <dd className="truncate font-medium text-foreground">{modelName(report.routing?.model_used ?? usage?.models?.generator)}</dd>
              {report.routing?.fell_back && <dd className="text-[10px] text-warning">fell back from {modelName(report.routing.primary_model)}</dd>}
            </div>
            <div className="rounded-lg bg-surface p-2.5">
              <dt className="text-[11px] text-muted-foreground"><MetricTip term="tokens">Tokens</MetricTip></dt>
              <dd className="font-medium tabular-nums text-foreground">
                {tokenTotal !== null ? `${compact(tokenTotal)} (${compact(usage!.prompt_tokens)} in / ${compact(usage!.completion_tokens)} out)` : usage?.llm_calls === 0 ? '0 — no model was called' : 'Not recorded'}
              </dd>
              {usage && <dd className="text-[10px] text-muted-foreground">{usage.llm_calls} model call{usage.llm_calls === 1 ? '' : 's'}, guardrails included</dd>}
            </div>
          </dl>
          <Button size="sm" variant="outline" onClick={onCompare} data-testid="compare-this-question">
            <GitCompareArrows className="size-3.5" /> Would another strategy do better?
          </Button>
        </div>
      </Collapsible>

      <Collapsible id="answer-quality" title="Answer quality" summary={grounding ? `${grounding.supported}/${grounding.total} sentences supported` : undefined}>
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <MetricTip term="estimated"><Badge variant="outline">Estimated</Badge></MetricTip>
            <span>judged by {modelName(quality.judge_model)} — there is no reference answer for a live question.</span>
          </div>
          {quality.not_measured_reason && <p className="text-xs text-warning">{quality.not_measured_reason}</p>}
          <dl className="grid grid-cols-2 gap-2">
            <Metric label="Grounding" term="grounding" value={grounding ? pct(grounding.score, 0) : undefined} caption={grounding ? `${grounding.supported} of ${grounding.total} sentences` : 'no checkable claim, or not measured'} />
            <Metric label="Faithfulness" term="faithfulness" value={score(quality.faithfulness)} caption={quality.faithfulness === null && report.citations.length === 0 ? 'nothing was cited' : undefined} />
            <Metric label="Relevancy" term="relevancy" value={score(quality.relevancy)} />
            <Metric label="Citation validity" term="citation_validity" value={pct(quality.citation_validity, 0)} />
          </dl>
          {unsupported.length > 0 && (
            <div className="rounded-lg border border-danger/40 bg-danger/10 p-2.5 text-xs" data-testid="unsupported-list">
              <p className="mb-1 font-medium text-foreground">{unsupported.length} sentence{unsupported.length === 1 ? '' : 's'} with no support in the retrieved text (also marked in the answer):</p>
              <ul className="flex list-disc flex-col gap-1 pl-4 text-muted-foreground">
                {unsupported.map((s) => <li key={s.text}>{s.text}</li>)}
              </ul>
            </div>
          )}
        </div>
      </Collapsible>

      <Collapsible id="answer-retrieval" title="Retrieval breakdown" term="rrf" summary={`${chunks.filter((c) => c.used).length}/${chunks.length} used`}>
        <div className="flex flex-col gap-3">
          <Funnel report={report} />
          {chunks.length > 0 && (
            <ul className="flex flex-col gap-1.5" data-testid="retrieved-chunks">
              {chunks.map((chunk) => (
                <ChunkRow key={chunk.chunk_id} chunk={chunk} hovered={hoveredChunk === chunk.chunk_id} onHover={onHoverChunk} />
              ))}
            </ul>
          )}
        </div>
      </Collapsible>

      <Collapsible id="answer-timeline" title="Trace timeline" summary={report.timings ? `${report.timings.length} stages` : undefined} defaultOpen={false}>
        <Timeline timings={report.timings ?? []} total={report.latency_ms} />
      </Collapsible>
    </div>
  )
}
