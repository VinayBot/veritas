import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Check, FlaskConical, GitCompareArrows, Square, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/page'
import { StatCard, type StatDelta } from '@/components/ui/stat-card'
import { DataTable, type Column } from '@/components/ui/data-table'
import { EmptyState, ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { InlineBar, ProgressBar } from '@/components/ui/progress-bar'
import { MetricTip } from '@/components/ui/metric-tip'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { CountUp } from '@/components/ui/count-up'
import { useCommands, type CommandPaletteItem } from '@/components/ui/command-palette'
import { ChartTable, EChart, axisStyle, baseOption, useChartTheme } from '@/components/charts/EChart'
import { CompareDialog } from '@/components/compare/CompareDialog'
import { useJob } from '@/hooks/useJob'
import { useStrategies } from '@/hooks/useStrategies'
import {
  ApiError,
  decideAdvisor,
  getAdvisor,
  getBenchmark,
  listBenchmarkRuns,
  listDatasets,
  runAdvisor,
  startBenchmark,
} from '@/lib/api/client'
import type { AdvisorResponse, BenchmarkRunResponse, CandidateResultOut, ConfigResultOut, EvalDataset, EvalSample } from '@/lib/api/types'
import type { GlossaryTerm } from '@/lib/glossary'
import { dateTime, modelName, ms, relativeTime, score } from '@/lib/format'
import { cn } from '@/lib/utils'

type MetricKey = 'faithfulness' | 'answer_relevancy' | 'precision_at_5' | 'recall_at_5' | 'ndcg_at_5' | 'correctness'

/** How each headline metric was scored. "Verified" needs ground truth from the eval set
 * (labelled relevant chunks or a reference answer); "Estimated" is a judge model's opinion. */
const METRICS: { key: MetricKey; label: string; term: GlossaryTerm; basis: 'verified' | 'estimated' }[] = [
  { key: 'faithfulness', label: 'Faithfulness', term: 'faithfulness', basis: 'estimated' },
  { key: 'answer_relevancy', label: 'Answer relevance', term: 'relevancy', basis: 'estimated' },
  { key: 'precision_at_5', label: 'Context precision@5', term: 'precision', basis: 'verified' },
  { key: 'recall_at_5', label: 'Context recall@5', term: 'recall', basis: 'verified' },
  { key: 'ndcg_at_5', label: 'Ranking nDCG@5', term: 'ndcg', basis: 'verified' },
  { key: 'correctness', label: 'Correctness', term: 'correctness', basis: 'verified' },
]
const KPI_KEYS: MetricKey[] = ['faithfulness', 'answer_relevancy', 'precision_at_5', 'recall_at_5']

function metric(c: ConfigResultOut | undefined, key: MetricKey): number | null {
  if (!c || c.skipped_reason) return null
  if (key === 'faithfulness' || key === 'answer_relevancy' || key === 'correctness') return c[key]
  const value = c.retrieval_metrics[key]
  return value === undefined ? null : value
}

/** How many questions a number rests on. */
function sampleCount(c: ConfigResultOut | undefined, key: MetricKey): number | undefined {
  if (!c) return undefined
  if (key === 'faithfulness' || key === 'correctness') return c.n_judged[key] ?? c.n_samples
  if (key === 'answer_relevancy') return c.n_judged.relevancy ?? c.n_judged.answer_relevancy ?? c.n_samples
  return c.retrieval_metrics.n ?? c.n_samples
}

/** The configuration a run's headline numbers describe: the recommended one, else the best
 * scoring one that actually ran. */
function headline(run: BenchmarkRunResponse | undefined): ConfigResultOut | undefined {
  if (!run) return undefined
  const ran = run.config_results.filter((c) => !c.skipped_reason)
  return (
    ran.find((c) => c.name === run.recommended_config) ??
    [...ran].sort((a, b) => (b.production_score ?? -1) - (a.production_score ?? -1))[0]
  )
}

type Band = 'High' | 'Medium' | 'Low'
function band(c: ConfigResultOut): Band | null {
  if (c.production_score === null) return null
  return c.production_score >= 0.7 ? 'High' : c.production_score >= 0.5 ? 'Medium' : 'Low'
}
const BAND_VARIANT: Record<Band, 'success' | 'warning' | 'destructive'> = { High: 'success', Medium: 'warning', Low: 'destructive' }

export function QualitySection({ documentId }: { documentId: string }) {
  const theme = useChartTheme()
  const strategies = useStrategies(documentId)
  const [runs, setRuns] = useState<BenchmarkRunResponse[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<BenchmarkRunResponse | null>(null)
  const [openStrategy, setOpenStrategy] = useState<string | null>(null)
  const [datasets, setDatasets] = useState<EvalDataset[] | null>(null)
  const [datasetChoice, setDatasetChoice] = useState<string>('latest')
  const [picked, setPicked] = useState<string[] | null>(null)
  const [includeSafety, setIncludeSafety] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [compareOpen, setCompareOpen] = useState(false)

  const names = useMemo(
    () => Object.fromEntries((strategies.data?.strategies ?? []).map((s) => [s.id, s.display_name])),
    [strategies.data],
  )
  const nameOf = useCallback((id: string) => names[id] ?? id.replace(/_/g, ' '), [names])

  const load = useCallback(() => {
    listBenchmarkRuns(documentId)
      .then((data) => {
        setRuns([...data.runs].sort((a, b) => a.created_at.localeCompare(b.created_at)))
        setError(null)
      })
      .catch(setError)
    listDatasets(documentId)
      .then((data) => setDatasets(data.datasets))
      .catch(() => setDatasets([]))
  }, [documentId])

  useEffect(() => {
    setRuns(null)
    setSelectedId(null)
    load()
  }, [load])

  const job = useJob(jobId, (finished) => {
    if (finished.status === 'done') {
      toast.success('Evaluation finished')
      setSelectedId(null)
    } else if (finished.status === 'failed') toast.error(finished.error ?? 'Evaluation failed')
    else toast.message('Evaluation cancelled — nothing was saved')
    load()
  })

  // Runs from the first harness were scored differently and are never mixed with current ones.
  const comparable = useMemo(() => (runs ?? []).filter((r) => r.harness_version === 2), [runs])
  const legacyCount = (runs?.length ?? 0) - comparable.length
  const selected = comparable.find((r) => r.id === selectedId) ?? comparable[comparable.length - 1]
  const selectedConfig = headline(selected)
  // A delta is only honest against the previous run on the same questions.
  const sameSet = useMemo(
    () => (selected ? comparable.filter((r) => r.dataset_id !== null && r.dataset_id === selected.dataset_id && r.created_at <= selected.created_at) : []),
    [comparable, selected],
  )
  const previous = sameSet.length >= 2 ? sameSet[sameSet.length - 2] : undefined

  useEffect(() => {
    setDetail(null)
    setOpenStrategy(null)
    if (!selected) return
    let cancelled = false
    getBenchmark(selected.id)
      .then((data) => !cancelled && setDetail(data))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [selected?.id]) // eslint-disable-line react-hooks/exhaustive-deps -- keyed on the run id

  const available = (strategies.data?.strategies ?? []).filter((s) => s.available)
  const defaultPick = useMemo(
    () => available.filter((s) => ['hybrid', 'hybrid_rerank', 'graph_rag'].includes(s.id)).map((s) => s.id),
    [available],
  )
  const chosen = picked ?? defaultPick
  const chosenSet = datasets?.find((d) => d.id === datasetChoice) ?? (datasetChoice === 'latest' ? datasets?.[0] : undefined)
  // The backend uses at most five questions per run (three for the agent strategies).
  const questions = Math.min(chosenSet?.item_count ?? 5, 5)
  const expectedSeconds = available
    .filter((s) => chosen.includes(s.id))
    .reduce((sum, s) => sum + ((s.measured_latency_ms ?? s.typical_latency_ms) / 1000) * (s.kind === 'agentic' ? Math.min(questions, 3) : questions) + 3 * questions, 0)

  async function start() {
    setConfirmOpen(false)
    try {
      const { job_id } = await startBenchmark({
        document_id: documentId,
        configs: chosen,
        dataset_id: datasetChoice === 'latest' || datasetChoice === 'new' ? null : datasetChoice,
        dataset_target_size: 5,
        include_safety: includeSafety,
      })
      setJobId(job_id)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not start the evaluation')
    }
  }

  const commands = useMemo<CommandPaletteItem[]>(
    () => [
      { id: 'run-eval', label: 'Run evaluation', group: 'Run', keywords: 'benchmark test quality', onSelect: () => setConfirmOpen(true) },
      { id: 'compare-strategies', label: 'Compare strategies…', group: 'Run', keywords: 'rag', onSelect: () => setCompareOpen(true) },
    ],
    [],
  )
  useCommands('evaluation-quality', commands)

  // ---- trend ----------------------------------------------------------------------------
  const trendOption = useMemo(() => {
    const rows = comparable.map((r) => ({ run: r, config: headline(r) }))
    return {
      ...baseOption(theme),
      color: theme.series,
      grid: { left: 40, right: 16, top: 36, bottom: 28 },
      legend: { ...(baseOption(theme).legend as object), top: 0, left: 0 },
      tooltip: {
        ...(baseOption(theme).tooltip as object),
        trigger: 'axis',
        formatter: (params: { dataIndex: number; marker: string; seriesName: string; value: number | null }[]) => {
          const row = rows[params[0].dataIndex]
          const cfg = row.run.run_config ?? {}
          const lines = params.map((p) => `${p.marker} ${p.seriesName}: <b>${p.value === null || p.value === undefined ? 'not measured' : p.value.toFixed(2)}</b>`)
          return [
            `<b>${dateTime(row.run.created_at)}</b>`,
            `${row.config ? nameOf(row.config.name) : '—'} · eval set v${row.run.dataset_version ?? '?'} · n=${row.run.n_items ?? '?'}`,
            ...lines,
            `<span style="opacity:.7">judge ${modelName(cfg.judge)} · generator ${modelName(cfg.generator)}</span>`,
            `<span style="opacity:.7">chunking ${cfg.chunking ?? '—'} · embedder ${cfg.embedding ?? '—'}</span>`,
          ].join('<br/>')
        },
      },
      xAxis: { type: 'category', boundaryGap: false, data: rows.map((r) => relativeTime(r.run.created_at)), ...axisStyle(theme), splitLine: { show: false } },
      yAxis: { type: 'value', min: 0, max: 1, ...axisStyle(theme) },
      series: METRICS.slice(0, 5).map((m, i) => ({
        name: m.label,
        type: 'line',
        smooth: 0.35,
        symbol: 'circle',
        symbolSize: 7,
        connectNulls: false,
        lineStyle: { width: 2.5, shadowBlur: 12, shadowColor: theme.series[i] },
        areaStyle: i === 0 ? { opacity: 0.12 } : undefined,
        emphasis: { focus: 'series' },
        data: rows.map((r) => metric(r.config, m.key)),
      })),
    }
  }, [comparable, theme, nameOf])

  // ---- radar + latency for the selected run ------------------------------------------------
  const ran = useMemo(() => (selected?.config_results ?? []).filter((c) => !c.skipped_reason), [selected])
  const radarOption = useMemo(
    () => ({
      ...baseOption(theme),
      color: theme.series,
      legend: { ...(baseOption(theme).legend as object), bottom: 0 },
      tooltip: { ...(baseOption(theme).tooltip as object) },
      radar: {
        radius: '62%',
        center: ['50%', '46%'],
        indicator: METRICS.slice(0, 5).map((m) => ({ name: m.label, max: 1 })),
        axisName: { color: theme.muted, fontSize: 10 },
        splitLine: { lineStyle: { color: theme.border } },
        splitArea: { show: false },
        axisLine: { lineStyle: { color: theme.border } },
      },
      series: [
        {
          type: 'radar',
          symbolSize: 4,
          areaStyle: { opacity: 0.1 },
          lineStyle: { width: 2 },
          // A metric that was not measured is drawn at the centre and named in the tooltip.
          data: ran.map((c) => ({ name: nameOf(c.name), value: METRICS.slice(0, 5).map((m) => metric(c, m.key) ?? 0) })),
        },
      ],
    }),
    [ran, theme, nameOf],
  )
  const latencyOption = useMemo(
    () => ({
      ...baseOption(theme),
      grid: { left: 8, right: 24, top: 28, bottom: 8, containLabel: true },
      legend: { ...(baseOption(theme).legend as object), top: 0, left: 0 },
      tooltip: { ...(baseOption(theme).tooltip as object), trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: number) => ms(v) ?? '—' },
      xAxis: { type: 'value', ...axisStyle(theme), axisLabel: { color: theme.muted, fontSize: 11, formatter: (v: number) => ms(v) ?? '' } },
      yAxis: { type: 'category', data: ran.map((c) => nameOf(c.name)), ...axisStyle(theme), splitLine: { show: false } },
      series: [
        { name: 'p50', type: 'bar', barMaxWidth: 12, itemStyle: { color: theme.live, borderRadius: 6 }, data: ran.map((c) => Math.round(c.p50_latency_ms)) },
        { name: 'p95', type: 'bar', barMaxWidth: 12, itemStyle: { color: theme.gold, borderRadius: 6 }, data: ran.map((c) => Math.round(c.p95_latency_ms)) },
      ],
    }),
    [ran, theme, nameOf],
  )

  // ---- table ----------------------------------------------------------------------------
  const num = (c: ConfigResultOut, key: MetricKey) => {
    const v = metric(c, key)
    return v === null ? <span className="text-muted-foreground">not measured</span> : v.toFixed(2)
  }
  const columns: Column<ConfigResultOut>[] = [
    {
      key: 'name',
      header: 'Strategy',
      sortValue: (c) => nameOf(c.name),
      render: (c) => (
        <span className="flex flex-wrap items-center gap-1.5 font-medium">
          {nameOf(c.name)}
          {selected?.recommended_config === c.name && <Badge variant="glow">recommended</Badge>}
          {c.skipped_reason && (
            <Badge variant="outline" title={c.skipped_reason}>
              skipped
            </Badge>
          )}
        </span>
      ),
    },
    {
      key: 'band',
      header: 'Verdict',
      tip: 'From the overall score: High is 0.70 or more, Medium 0.50 or more, Low below that.',
      sortValue: (c) => c.production_score,
      render: (c) => {
        const b = band(c)
        return b ? <Badge variant={BAND_VARIANT[b]}>{b}</Badge> : <span className="text-muted-foreground">—</span>
      },
    },
    {
      key: 'score',
      header: 'Overall score',
      term: 'production_score',
      sortValue: (c) => c.production_score,
      render: (c) => (c.production_score === null ? <span className="text-muted-foreground">not measured</span> : <InlineBar value={c.production_score} className="min-w-28" />),
    },
    ...METRICS.map<Column<ConfigResultOut>>((m) => ({
      key: m.key,
      header: m.label.replace('Context ', '').replace('Ranking ', '').replace('Answer ', ''),
      term: m.term,
      align: 'right',
      sortValue: (c) => metric(c, m.key),
      render: (c) => num(c, m.key),
    })),
    { key: 'p50', header: 'p50', term: 'p50', align: 'right', sortValue: (c) => c.p50_latency_ms, render: (c) => (c.skipped_reason ? '—' : ms(c.p50_latency_ms)) },
    { key: 'p95', header: 'p95', term: 'p95', align: 'right', sortValue: (c) => c.p95_latency_ms, render: (c) => (c.skipped_reason ? '—' : ms(c.p95_latency_ms)) },
    {
      key: 'tokens',
      header: 'Tokens / answer',
      term: 'tokens',
      align: 'right',
      sortValue: (c) => (c.avg_prompt_tokens ?? 0) + (c.avg_completion_tokens ?? 0) || undefined,
      render: (c) => (c.avg_prompt_tokens === null ? <span className="text-muted-foreground">—</span> : Math.round(c.avg_prompt_tokens + (c.avg_completion_tokens ?? 0))),
    },
    { key: 'n', header: 'n', tip: 'How many questions this row was measured on.', align: 'right', sortValue: (c) => c.n_samples, render: (c) => c.n_samples },
    {
      key: 'gate',
      header: 'Gates',
      term: 'hard_gates',
      sortValue: (c) => (c.passes_hard_gates ? 1 : 0),
      render: (c) =>
        c.skipped_reason ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <Badge variant={c.passes_hard_gates ? 'success' : 'destructive'} title={c.gate_failures.join(' · ') || undefined}>
            {c.passes_hard_gates ? 'pass' : `${c.gate_failures.length} missed`}
          </Badge>
        ),
    },
  ]

  if (error) return <ErrorState error={error} action={<Button size="sm" variant="outline" onClick={load}>Retry</Button>} />

  const runControl = (
    <Panel
      title="Run evaluation"
      description="Asks the eval-set questions through each chosen strategy and scores the answers. Runs in the background; you can leave this tab."
      testId="eval-run-panel"
    >
      {job.active ? (
        <div className="flex flex-col gap-3" data-testid="eval-progress">
          <ProgressBar value={job.progress} label="Evaluation progress" tone="live" />
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span className="min-w-0 truncate">{job.message ?? 'Working…'}</span>
            <span className="tabular-nums text-foreground">{Math.round(job.progress * 100)}%</span>
          </div>
          <Button size="sm" variant="outline" onClick={job.cancel} data-testid="eval-cancel">
            <Square className="size-3.5" /> Cancel run
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Questions
            <select
              value={datasetChoice}
              onChange={(e) => setDatasetChoice(e.target.value)}
              className="rounded-lg border border-border bg-surface-raised px-2.5 py-1.5 text-sm text-foreground"
              data-testid="eval-dataset-select"
            >
              <option value="latest">{datasets?.[0] ? `Latest question set (v${datasets[0].version}, uses ${Math.min(datasets[0].item_count, 5)} of ${datasets[0].item_count})` : 'Write 5 new questions from the document'}</option>
              {(datasets ?? []).slice(1).map((d) => (
                <option key={d.id} value={d.id}>
                  Eval set v{d.version} · {d.item_count} questions
                </option>
              ))}
            </select>
          </label>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1 text-xs text-muted-foreground">Strategies</legend>
            {strategies.data === null ? (
              <LoadingState rows={3} label="Loading strategies" />
            ) : (
              strategies.data.strategies.map((s) => (
                <label key={s.id} className={cn('flex items-center gap-2 text-xs', s.available ? 'text-foreground' : 'text-muted-foreground')} title={s.unavailable_reason ?? s.best_for}>
                  <input
                    type="checkbox"
                    className="accent-(--color-accent)"
                    disabled={!s.available}
                    checked={s.available && chosen.includes(s.id)}
                    onChange={(e) => setPicked(e.target.checked ? [...chosen, s.id] : chosen.filter((id) => id !== s.id))}
                  />
                  {s.display_name}
                  {!s.available && <span>· unavailable</span>}
                </label>
              ))
            )}
          </fieldset>
          <label className="flex items-center gap-2 text-xs text-foreground" title="Adds the red-team suite and a PII leak scan. Needed for the safety gates; adds a few minutes.">
            <input type="checkbox" className="accent-(--color-accent)" checked={includeSafety} onChange={(e) => setIncludeSafety(e.target.checked)} />
            Include safety checks
          </label>
          <Button onClick={() => setConfirmOpen(true)} disabled={chosen.length === 0} data-testid="run-eval-button">
            <FlaskConical className="size-4" /> Run evaluation
          </Button>
          <Button variant="outline" size="sm" onClick={() => setCompareOpen(true)} disabled={!strategies.data}>
            <GitCompareArrows className="size-3.5" /> Compare strategies
          </Button>
        </div>
      )}
    </Panel>
  )

  return (
    <div className="flex flex-col gap-6" data-testid="eval-quality">
      <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {KPI_KEYS.map((key) => {
          const m = METRICS.find((x) => x.key === key)!
          const value = metric(selectedConfig, key)
          const before = metric(headline(previous), key)
          const trend = sameSet.map((r) => metric(headline(r), key)).filter((v): v is number => v !== null)
          const delta: StatDelta | undefined =
            value !== null && before !== null && Math.abs(value - before) >= 0.005
              ? { good: value > before, direction: value > before ? 'up' : 'down', label: `${value > before ? '+' : ''}${(value - before).toFixed(2)} vs previous run` }
              : undefined
          const n = sampleCount(selectedConfig, key)
          return (
            <StatCard
              key={key}
              label={m.label}
              term={m.term}
              loading={runs === null}
              value={value === null ? undefined : <CountUp value={value} format={(x) => x.toFixed(2)} />}
              emptyLabel={selected ? 'Not measured' : 'No evaluation run yet'}
              delta={delta}
              trend={trend.length >= 2 ? trend : undefined}
              caption={
                selected && value !== null ? (
                  <span>
                    <MetricTip term={m.basis} className="text-muted-foreground">
                      {m.basis === 'verified' ? 'Verified' : 'Estimated'}
                    </MetricTip>{' '}
                    · n={n ?? '—'} · eval set v{selected.dataset_version ?? '?'}
                  </span>
                ) : undefined
              }
              className="lacquer-card"
              testId={`eval-kpi-${key}`}
            />
          )
        })}
      </div>

      {selected && (
        <p className="-mt-2 text-xs text-muted-foreground" data-testid="eval-provenance">
          Showing the run from <span className="text-foreground">{dateTime(selected.created_at)}</span>
          {selectedConfig && (
            <>
              {' '}
              · headline strategy <span className="text-foreground">{nameOf(selectedConfig.name)}</span>
            </>
          )}{' '}
          · {selected.n_items ?? '?'} questions from eval set v{selected.dataset_version ?? '?'} · judge {modelName(selected.run_config?.judge)} · generator{' '}
          {modelName(selected.run_config?.generator)}
          {selected.duration_ms !== null && <> · took {ms(selected.duration_ms)}</>}
          {!previous && ' · no earlier run on the same questions, so no change is shown'}
          {legacyCount > 0 && ` · ${legacyCount} older run${legacyCount === 1 ? '' : 's'} from the previous scoring method ${legacyCount === 1 ? 'is' : 'are'} hidden because the numbers are not comparable`}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-6">
          <Panel
            title="Quality across runs"
            description="Each point is one evaluation run's headline strategy. Hover for the configuration that produced it; click a point to inspect that run."
            testId="eval-trend"
          >
            {runs === null ? (
              <LoadingState shape="chart" label="Loading evaluation runs" />
            ) : comparable.length === 0 ? (
              <EmptyState
                title="No evaluation has been run on this document"
                description="An evaluation generates questions with known answers from the document, asks them through each strategy, and scores the results. Nothing is shown until that has really happened."
                action={<Button size="sm" onClick={() => setConfirmOpen(true)}>Run evaluation</Button>}
              />
            ) : (
              <EChart
                option={trendOption}
                label="Quality metrics across evaluation runs"
                onPointClick={(p) => setSelectedId(comparable[p.dataIndex]?.id ?? null)}
                table={
                  <ChartTable
                    caption="Quality metrics by evaluation run"
                    head={['Run', 'Strategy', ...METRICS.slice(0, 5).map((m) => m.label), 'n']}
                    rows={comparable.map((r) => {
                      const c = headline(r)
                      return [dateTime(r.created_at), c ? nameOf(c.name) : '—', ...METRICS.slice(0, 5).map((m) => score(metric(c, m.key)) ?? 'not measured'), r.n_items ?? '—']
                    })}
                  />
                }
              />
            )}
          </Panel>

          {selected && (
            <>
              <Panel
                title="Strategies in this run"
                description="Sort by any column. Click a row to see how each question went."
                testId="eval-strategy-table"
              >
                <DataTable
                  caption="Evaluation results by strategy"
                  columns={columns}
                  rows={selected.config_results}
                  rowKey={(c) => c.name}
                  initialSort={{ key: 'score', direction: 'desc' }}
                  onRowClick={(c) => setOpenStrategy((prev) => (prev === c.name ? null : c.name))}
                />
                {openStrategy && <Samples name={nameOf(openStrategy)} samples={detail?.config_results.find((c) => c.name === openStrategy)?.samples} onClose={() => setOpenStrategy(null)} />}
              </Panel>

              {ran.length > 0 && (
                <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                  <Panel title="Strategy shape" description="The same five metrics per strategy. A larger, rounder shape is better on every axis.">
                    <EChart
                      option={radarOption}
                      label="Radar chart comparing strategies on five quality metrics"
                      height={300}
                      table={
                        <ChartTable
                          caption="Quality metrics by strategy"
                          head={['Strategy', ...METRICS.slice(0, 5).map((m) => m.label)]}
                          rows={ran.map((c) => [nameOf(c.name), ...METRICS.slice(0, 5).map((m) => score(metric(c, m.key)) ?? 'not measured')])}
                        />
                      }
                    />
                  </Panel>
                  <Panel title="Speed" description="Measured answer latency in this run: the median and the slow tail.">
                    <EChart
                      option={latencyOption}
                      label="Bar chart of p50 and p95 latency by strategy"
                      height={300}
                      table={<ChartTable caption="Latency by strategy" head={['Strategy', 'p50', 'p95', 'n']} rows={ran.map((c) => [nameOf(c.name), ms(c.p50_latency_ms), ms(c.p95_latency_ms), c.n_samples])} />}
                    />
                  </Panel>
                </div>
              )}
            </>
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-6">
          {runControl}
          <GateStatus run={selected} config={selectedConfig} nameOf={nameOf} />
          <ChunkingAdvisor documentId={documentId} />
        </div>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Run an evaluation?"
        description={
          <>
            {chosen.length} strateg{chosen.length === 1 ? 'y' : 'ies'} × {chosenSet ? `${Math.min(chosenSet.item_count, 5)} questions (set v${chosenSet.version})` : '5 new questions'}
            {includeSafety ? ', plus the red-team suite and a PII leak scan' : ''}.
          </>
        }
        cost={
          <>
            Roughly {expectedSeconds >= 90 ? `${Math.round(expectedSeconds / 60)} minutes` : `${Math.max(1, Math.round(expectedSeconds))} seconds`} of answering, plus judging — an
            estimate from each strategy’s {available.some((s) => s.measured_latency_ms !== null) ? 'measured' : 'typical'} latency. It keeps the local models busy; chat will be slow until it
            finishes. You can cancel at any time.
          </>
        }
        confirmLabel="Start run"
        onConfirm={() => void start()}
      />
      {compareOpen && strategies.data && (
        <CompareDialog
          open
          onOpenChange={(open) => !open && setCompareOpen(false)}
          documentId={documentId}
          strategies={strategies.data.strategies}
          defaultStrategy={strategies.data.default}
          onAdopted={() => strategies.refresh()}
        />
      )}
    </div>
  )
}

function Samples({ name, samples, onClose }: { name: string; samples: EvalSample[] | undefined; onClose: () => void }) {
  const cell = (v: number | null) => (v === null ? <span className="text-muted-foreground">—</span> : v.toFixed(2))
  const columns: Column<EvalSample>[] = [
    { key: 'q', header: 'Question', sortValue: (s) => s.question, render: (s) => <span className="block max-w-md whitespace-normal" title={s.answer}>{s.question}</span> },
    { key: 'cat', header: 'Type', sortValue: (s) => s.category, render: (s) => <Badge variant="outline">{s.category.replace(/_/g, ' ')}</Badge> },
    { key: 'outcome', header: 'Outcome', sortValue: (s) => s.outcome, render: (s) => <Badge variant={s.outcome === 'answered' ? 'success' : 'warning'}>{s.outcome}</Badge> },
    { key: 'f', header: 'Faithfulness', term: 'faithfulness', align: 'right', sortValue: (s) => s.faithfulness, render: (s) => cell(s.faithfulness) },
    { key: 'r', header: 'Relevance', term: 'relevancy', align: 'right', sortValue: (s) => s.relevancy, render: (s) => cell(s.relevancy) },
    { key: 'c', header: 'Correctness', term: 'correctness', align: 'right', sortValue: (s) => s.correctness, render: (s) => cell(s.correctness) },
    { key: 'cit', header: 'Citations', align: 'right', sortValue: (s) => s.citations, render: (s) => s.citations },
    { key: 'lat', header: 'Latency', align: 'right', sortValue: (s) => s.latency_ms, render: (s) => ms(s.latency_ms) },
  ]
  return (
    <div className="mt-4 rounded-xl border border-border bg-surface-raised p-4" data-testid="eval-samples">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold text-foreground">{name}: question by question</h3>
        <button type="button" onClick={onClose} aria-label="Close question list" className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>
      {samples === undefined ? (
        <LoadingState shape="table" rows={3} label="Loading per-question results" />
      ) : samples.length === 0 ? (
        <EmptyState compact title="No per-question records" description="Answers are only generated and judged for a sample of questions; this strategy has retrieval metrics only." />
      ) : (
        <DataTable caption={`Per-question results for ${name}`} columns={columns} rows={samples} rowKey={(s) => s.item_id} initialSort={{ key: 'f', direction: 'asc' }} />
      )}
    </div>
  )
}

function GateStatus({ run, config, nameOf }: { run: BenchmarkRunResponse | undefined; config: ConfigResultOut | undefined; nameOf: (id: string) => string }) {
  const rows: { label: string; value: string | undefined; ok: boolean | null }[] = [
    { label: 'Faithfulness ≥ 0.85', value: score(config?.faithfulness), ok: config?.faithfulness === null || config?.faithfulness === undefined ? null : config.faithfulness >= 0.85 },
    { label: 'p95 latency ≤ 15s', value: config ? ms(config.p95_latency_ms) : undefined, ok: config ? config.p95_latency_ms <= 15_000 : null },
    {
      label: 'Attack block rate ≥ 95%',
      value: run?.injection_block_rate === null || run?.injection_block_rate === undefined ? undefined : `${(run.injection_block_rate * 100).toFixed(0)}%`,
      ok: run?.injection_block_rate === null || run?.injection_block_rate === undefined ? null : run.injection_block_rate >= 0.95,
    },
    {
      label: 'PII leaks = 0',
      value: run?.pii_leak_count === null || run?.pii_leak_count === undefined ? undefined : String(run.pii_leak_count),
      ok: run?.pii_leak_count === null || run?.pii_leak_count === undefined ? null : run.pii_leak_count === 0,
    },
  ]
  return (
    <Panel title="Release gates" term="hard_gates" description={config ? `For ${nameOf(config.name)} in the selected run.` : undefined} testId="eval-gates">
      {!run ? (
        <EmptyState compact title="Nothing to gate yet" description="Gates are checked against an evaluation run." />
      ) : (
        <ul className="flex flex-col gap-2 text-xs">
          {rows.map((r) => (
            <li key={r.label} className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-foreground">
                <span className={cn('flex size-4 items-center justify-center rounded-full', r.ok === null ? 'bg-surface-raised text-muted-foreground' : r.ok ? 'bg-success/15 text-success' : 'bg-danger/15 text-danger')} aria-hidden="true">
                  {r.ok === null ? '–' : r.ok ? <Check className="size-3" /> : <X className="size-3" />}
                </span>
                {r.label}
              </span>
              <span className="tabular-nums text-muted-foreground">{r.value ?? 'not measured'}</span>
            </li>
          ))}
          {config && config.gate_failures.length > 0 && <li className="mt-1 text-danger">{config.gate_failures.join(' · ')}</li>}
        </ul>
      )}
    </Panel>
  )
}

/** The chunking tournament: re-chunks the document several ways, measures retrieval on each,
 * and offers to switch if one clearly wins. */
function ChunkingAdvisor({ documentId }: { documentId: string }) {
  const [advisor, setAdvisor] = useState<AdvisorResponse | null | undefined>(undefined)
  const [busy, setBusy] = useState<'run' | 'accept' | 'ignore' | null>(null)

  useEffect(() => {
    let cancelled = false
    setAdvisor(undefined)
    getAdvisor(documentId)
      .then((data) => !cancelled && setAdvisor(data))
      .catch(() => !cancelled && setAdvisor(null))
    return () => {
      cancelled = true
    }
  }, [documentId])

  async function act(kind: 'run' | 'accept' | 'ignore') {
    setBusy(kind)
    try {
      const data = kind === 'run' ? await runAdvisor(documentId) : await decideAdvisor(documentId, kind)
      setAdvisor(data)
      if (kind === 'accept') toast.success('Document re-indexed with the suggested chunking')
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The chunking advisor failed')
    } finally {
      setBusy(null)
    }
  }

  const candidates: CandidateResultOut[] = advisor ? (advisor.candidates.length > 0 ? advisor.candidates : [advisor.baseline, advisor.suggested]) : []
  const best = Math.max(0.0001, ...candidates.map((c) => c.composite_score))
  return (
    <Panel
      title="Chunking advisor"
      description="Cuts the document up several ways and measures which is easiest to search."
      actions={
        <Button size="xs" variant="outline" disabled={busy !== null} onClick={() => void act('run')}>
          {busy === 'run' ? 'Measuring…' : advisor ? 'Re-run' : 'Run'}
        </Button>
      }
      testId="chunking-advisor"
    >
      {advisor === undefined || busy === 'run' ? (
        <LoadingState rows={4} label="Loading chunking results" />
      ) : advisor === null ? (
        <EmptyState compact title="Not measured for this document" description="Run it to compare chunking methods on real retrieval questions. Takes a minute or two." />
      ) : (
        <div className="flex flex-col gap-3">
          <ul className="flex flex-col gap-2">
            {[...candidates]
              .sort((a, b) => b.composite_score - a.composite_score)
              .map((c) => (
                <li key={c.name} className="flex flex-col gap-1 text-xs">
                  <span className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 text-foreground">
                      {c.chunking_strategy.replace(/_/g, ' ')}
                      {c.name === advisor.suggested.name && <Badge variant="glow">best</Badge>}
                      {c.name === advisor.baseline.name && <Badge variant="outline">current</Badge>}
                    </span>
                    <span className="tabular-nums text-muted-foreground" title={`nDCG@5 ${(c.retrieval_metrics.ndcg_at_5 ?? 0).toFixed(3)} · ${c.index_size} chunks · n=${c.n_samples}`}>
                      {c.composite_score.toFixed(3)}
                    </span>
                  </span>
                  <span className="h-1 overflow-hidden rounded-pill bg-surface-raised" aria-hidden="true">
                    <span className="block h-full origin-left rounded-pill bg-gold transition-transform duration-large ease-enter" style={{ transform: `scaleX(${c.composite_score / best})` }} />
                  </span>
                </li>
              ))}
          </ul>
          {advisor.rationale.length > 0 && <p className="text-xs text-muted-foreground">{advisor.rationale[0]}</p>}
          {advisor.decision === null && advisor.suggested.name !== advisor.baseline.name ? (
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={busy !== null} onClick={() => void act('accept')}>
                <Check className="size-3.5" /> Use {advisor.suggested.chunking_strategy.replace(/_/g, ' ')} (+{advisor.gain_ndcg_points.toFixed(1)} nDCG pts)
              </Button>
              <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void act('ignore')}>
                Keep current
              </Button>
            </div>
          ) : (
            advisor.decision && <Badge variant="outline" className="self-start">you chose to {advisor.decision === 'accept' ? 'switch' : 'keep the current chunking'}</Badge>
          )}
        </div>
      )}
    </Panel>
  )
}
