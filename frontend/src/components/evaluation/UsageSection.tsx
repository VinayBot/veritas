import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/page'
import { StatCard } from '@/components/ui/stat-card'
import { CountUp } from '@/components/ui/count-up'
import { Segmented } from '@/components/ui/segmented'
import { EmptyState, ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { MetricTip } from '@/components/ui/metric-tip'
import { ChartTable, EChart } from '@/components/charts/EChart'
import { axisStyle, baseOption, useChartTheme } from '@/components/charts/chart-theme'
import { usePolling } from '@/hooks/usePolling'
import { getAnalytics } from '@/lib/api/client'
import type { GlossaryTerm } from '@/lib/glossary'
import { bytes, compact, ms, pct, relativeTime, score } from '@/lib/format'

type Window = '7' | '14' | '30'

/** What real questions looked like over the window: volume, speed, quality and failures. All
 * of it is read from stored answers and runs; nothing here is from an evaluation set. */
export function UsageSection() {
  const [days, setDays] = useState<Window>('14')
  const navigate = useNavigate()
  const theme = useChartTheme()
  const { data, error, loading, refresh, updatedAt } = usePolling(() => getAnalytics(Number(days)), { intervalMs: 30_000 })
  // usePolling keeps the fetcher in a ref, so changing the window needs an explicit refresh.
  const changeWindow = (next: Window) => {
    setDays(next)
    window.setTimeout(refresh, 0)
  }

  const q = data?.queries
  const byDay = useMemo(() => q?.by_day ?? [], [q])
  const hasQueries = (q?.in_window ?? 0) > 0

  const volumeOption = useMemo(
    () => ({
      ...baseOption(theme),
      grid: { left: 36, right: 40, top: 36, bottom: 28 },
      legend: { ...(baseOption(theme).legend as object), top: 0, left: 0 },
      tooltip: { ...(baseOption(theme).tooltip as object), trigger: 'axis' },
      xAxis: { type: 'category', data: byDay.map((d) => d.date.slice(5)), ...axisStyle(theme), splitLine: { show: false } },
      yAxis: [
        { type: 'value', minInterval: 1, ...axisStyle(theme) },
        { type: 'value', min: 0, max: 1, ...axisStyle(theme), splitLine: { show: false } },
      ],
      series: [
        {
          name: 'Questions',
          type: 'bar',
          barMaxWidth: 22,
          itemStyle: { borderRadius: [6, 6, 0, 0], color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: theme.accent }, { offset: 1, color: 'transparent' }] } },
          data: byDay.map((d) => d.queries),
        },
        { name: 'Faithfulness (estimated)', type: 'line', yAxisIndex: 1, smooth: 0.3, symbolSize: 6, connectNulls: false, lineStyle: { width: 2.5, color: theme.gold }, itemStyle: { color: theme.gold }, data: byDay.map((d) => d.faithfulness) },
        { name: 'Sentences supported', type: 'line', yAxisIndex: 1, smooth: 0.3, symbolSize: 6, connectNulls: false, lineStyle: { width: 2.5, color: theme.live }, itemStyle: { color: theme.live }, data: byDay.map((d) => d.grounding) },
      ],
    }),
    [byDay, theme],
  )

  const mix = useMemo(() => q?.strategy_mix ?? [], [q])
  const mixOption = useMemo(
    () => ({
      ...baseOption(theme),
      color: theme.series,
      legend: { ...(baseOption(theme).legend as object), bottom: 0 },
      tooltip: { ...(baseOption(theme).tooltip as object), trigger: 'item', formatter: '{b}: <b>{c}</b> ({d}%)' },
      series: [
        {
          type: 'pie',
          radius: ['52%', '76%'],
          center: ['50%', '44%'],
          padAngle: 3,
          itemStyle: { borderRadius: 8 },
          label: { show: true, position: 'center', formatter: () => `${q?.in_window ?? 0}\nanswers`, color: theme.foreground, fontSize: 15, lineHeight: 20, fontWeight: 600 },
          data: mix.map((m) => ({ name: m.display_name, value: m.count })),
        },
      ],
    }),
    [mix, q?.in_window, theme],
  )

  const stages = useMemo(() => q?.latency_by_stage ?? [], [q])
  const stageOption = useMemo(
    () => ({
      ...baseOption(theme),
      grid: { left: 8, right: 24, top: 28, bottom: 8, containLabel: true },
      legend: { ...(baseOption(theme).legend as object), top: 0, left: 0 },
      tooltip: { ...(baseOption(theme).tooltip as object), trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v: number) => ms(v) ?? '—' },
      xAxis: { type: 'value', ...axisStyle(theme), axisLabel: { color: theme.muted, fontSize: 11, formatter: (v: number) => ms(v) ?? '' } },
      yAxis: { type: 'category', inverse: true, data: stages.map((s) => s.stage.replace(/_/g, ' ')), ...axisStyle(theme), splitLine: { show: false } },
      series: [
        { name: 'p50', type: 'bar', barMaxWidth: 10, itemStyle: { color: theme.live, borderRadius: 6 }, data: stages.map((s) => (s.p50 === null ? null : Math.round(s.p50))) },
        { name: 'p95', type: 'bar', barMaxWidth: 10, itemStyle: { color: theme.gold, borderRadius: 6 }, data: stages.map((s) => (s.p95 === null ? null : Math.round(s.p95))) },
      ],
    }),
    [stages, theme],
  )

  if (error && !data) return <ErrorState error={error} action={<Button size="sm" variant="outline" onClick={refresh}>Retry</Button>} />

  const quality = data?.quality
  const rel = data?.reliability
  const reliabilityRows: { label: string; value: string | number | undefined; term?: GlossaryTerm; tip?: string }[] = rel
    ? [
        { label: 'Answer runs', value: rel.runs },
        { label: 'Failed', value: `${rel.failed}${rel.failure_rate !== null ? ` (${pct(rel.failure_rate)})` : ''}` },
        { label: 'Cancelled by you', value: rel.cancelled },
        { label: 'Blocked by guardrails', value: rel.blocked },
        { label: 'Declined to answer', value: rel.abstained, tip: 'The system said it could not answer from the document rather than guess.' },
        { label: 'Retried on a faster model', value: `${rel.retried_after_timeout}${rel.retry_rate !== null ? ` (${pct(rel.retry_rate)})` : ''}`, tip: 'The first model timed out and a smaller one answered instead.' },
        {
          label: 'Agent searched or rewrote again',
          term: 'retry_rate',
          value: rel.agent_retry_rate === null ? undefined : `${pct(rel.agent_retry_rate)} of ${rel.turns_with_loop_data}`,
        },
      ]
    : []

  return (
    <div className="flex flex-col gap-6" data-testid="eval-usage">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Real questions asked in Workspace{updatedAt ? ` · updated ${relativeTime(updatedAt)}` : ''}. Scores here are{' '}
          <MetricTip term="estimated" className="text-muted-foreground">
            estimated
          </MetricTip>
          : no reference answers exist for live questions.
        </p>
        <Segmented
          label="Time window"
          value={days}
          onChange={changeWindow}
          options={[
            { value: '7', label: '7 days' },
            { value: '14', label: '14 days' },
            { value: '30', label: '30 days' },
          ]}
        />
      </div>

      <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Questions answered"
          loading={loading && !data}
          value={q ? <CountUp value={q.in_window} /> : undefined}
          caption={q ? `${compact(q.all_time)} all time · ${q.cache_hits} from cache` : undefined}
          trend={byDay.length >= 2 ? byDay.map((d) => d.queries) : undefined}
          className="lacquer-card"
          testId="usage-kpi-questions"
        />
        <StatCard
          label="Median answer time"
          term="p50"
          loading={loading && !data}
          value={q && q.latency_ms.p50 !== null ? ms(q.latency_ms.p50) : undefined}
          emptyLabel="No answers in this window"
          caption={q && q.latency_ms.p95 !== null ? `p95 ${ms(q.latency_ms.p95)} · n=${q.latency_ms.n}` : undefined}
          className="lacquer-card"
        />
        <StatCard
          label="Faithfulness"
          term="faithfulness"
          loading={loading && !data}
          value={quality && quality.faithfulness !== null ? <CountUp value={quality.faithfulness} format={(x) => x.toFixed(2)} /> : undefined}
          emptyLabel={hasQueries ? 'Not measured' : 'No answers in this window'}
          caption={quality && quality.grounding !== null ? `Estimated · ${pct(quality.grounding, 0)} of sentences supported` : quality?.faithfulness !== null && quality ? 'Estimated' : undefined}
          trend={byDay.map((d) => d.faithfulness).filter((v): v is number => v !== null).length >= 2 ? byDay.map((d) => d.faithfulness).filter((v): v is number => v !== null) : undefined}
          className="lacquer-card"
        />
        <StatCard
          label="Answers with no citation"
          term="zero_citation"
          loading={loading && !data}
          value={quality && quality.zero_citation_rate !== null ? pct(quality.zero_citation_rate, 0) : undefined}
          emptyLabel="No answers in this window"
          caption={quality && quality.answered > 0 ? `${quality.zero_citation_answers} of ${quality.answered} · ${score(quality.avg_citations, 1) ?? '—'} citations on average` : undefined}
          className="lacquer-card"
        />
      </div>

      {data && !hasQueries ? (
        <Panel>
          <EmptyState
            title={`No questions were asked in the last ${days} days`}
            description="Usage charts are drawn from real answers only. Ask something in Workspace and they fill in."
            action={<Button size="sm" onClick={() => navigate('/app')}>Go to Workspace</Button>}
          />
        </Panel>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <Panel title="Volume and quality by day" description="Bars are questions per day; lines are that day's average scores, where any were measured." className="xl:col-span-2" testId="usage-volume">
              {!data ? (
                <LoadingState shape="chart" label="Loading usage" />
              ) : (
                <EChart
                  option={volumeOption}
                  label="Questions per day with average faithfulness and grounding"
                  table={
                    <ChartTable
                      caption="Usage by day"
                      head={['Day', 'Questions', 'Faithfulness', 'n', 'Sentences supported', 'n']}
                      rows={byDay.map((d) => [d.date, d.queries, score(d.faithfulness) ?? 'not measured', d.faithfulness_n, pct(d.grounding, 0) ?? 'not measured', d.grounding_n])}
                    />
                  }
                />
              )}
            </Panel>
            <Panel title="Strategy mix" description="Which retrieval strategies actually answered." testId="usage-mix">
              {!data ? (
                <LoadingState shape="chart" label="Loading strategy mix" />
              ) : (
                <EChart
                  option={mixOption}
                  label="Share of answers by strategy"
                  table={<ChartTable caption="Answers by strategy" head={['Strategy', 'Answers', 'Share']} rows={mix.map((m) => [m.display_name, m.count, pct(m.share, 0)])} />}
                />
              )}
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <Panel
              title="Where the time goes"
              description={q ? `Time per pipeline stage, from the ${q.reports_with_stage_timings} answers that recorded stage timings.` : undefined}
              className="xl:col-span-2"
              testId="usage-stages"
            >
              {!data ? (
                <LoadingState shape="chart" label="Loading stage timings" />
              ) : stages.length === 0 ? (
                <EmptyState compact title="No stage timings recorded in this window" />
              ) : (
                <EChart
                  option={stageOption}
                  label="Median and tail latency by pipeline stage"
                  height={Math.max(220, stages.length * 34 + 60)}
                  table={<ChartTable caption="Latency by stage" head={['Stage', 'p50', 'p95', 'n']} rows={stages.map((s) => [s.stage, ms(s.p50), ms(s.p95), s.n])} />}
                />
              )}
            </Panel>
            <Panel title="Reliability" description="What happened to every answer run in the window." testId="usage-reliability">
              {!rel ? (
                <LoadingState rows={6} label="Loading reliability" />
              ) : (
                <dl className="flex flex-col gap-2 text-xs">
                  {reliabilityRows.map((r) => (
                    <div key={r.label} className="flex items-center justify-between gap-3 border-b border-border/60 pb-2 last:border-0 last:pb-0">
                      <dt className="text-muted-foreground">
                        <MetricTip term={r.term} tip={r.tip}>
                          {r.label}
                        </MetricTip>
                      </dt>
                      <dd className="tabular-nums text-foreground">{r.value ?? 'not measured'}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </Panel>
          </div>
        </>
      )}

      {data && (
        <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Tokens per answer" term="tokens" value={q?.avg_tokens_per_answer ? compact(q.avg_tokens_per_answer) : undefined} caption={q ? `from ${q.reports_with_token_counts} answers with counts` : undefined} />
          <StatCard label="Chunks indexed" term="chunk" value={compact(data.corpus.chunks)} caption={`${compact(data.corpus.tokens)} tokens · ${data.corpus.variant_chunks} in alternative indexes`} />
          <StatCard
            label="Index size on disk"
            value={bytes(data.corpus.index_bytes.vectors + data.corpus.index_bytes.database + data.corpus.index_bytes.graph)}
            caption={`vectors ${bytes(data.corpus.index_bytes.vectors)} · database ${bytes(data.corpus.index_bytes.database)} · graph ${bytes(data.corpus.index_bytes.graph)}`}
          />
          <StatCard label="Embedding model" term="embedding" value={<span className="text-base">{data.corpus.embedding_model}</span>} caption="used for every document in the index" />
        </div>
      )}
    </div>
  )
}
