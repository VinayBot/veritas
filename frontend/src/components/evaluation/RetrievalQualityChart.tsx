import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { Settings } from 'lucide-react'
import type { BenchmarkRunResponse } from '@/lib/api/types'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const SERIES_DEFS = [
  { key: 'recall_at_5', label: 'Recall@5', color: '#60a5fa' },
  { key: 'mrr', label: 'MRR', color: '#8b5cf6' },
  { key: 'ndcg_at_5', label: 'nDCG@5', color: '#e3a6ff' },
  { key: 'faithfulness', label: 'Faithfulness', color: '#f4b6a0' },
] as const

export interface RetrievalQualityChartProps {
  runs: BenchmarkRunResponse[]
}

/** EV-4: "Retrieval quality by run" — x = real benchmark runs, series = Recall@5/MRR/nDCG@5/
 * Faithfulness for that run's recommended config (the one the app would actually ship),
 * smooth splines with point dots, an HTML legend (coloured dots, toggles series), no
 * gridlines. Modular tree-shaken echarts/core import, matching the one existing real usage
 * site in this codebase (future-phase-previews.tsx). */
export function RetrievalQualityChart({ runs }: RetrievalQualityChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const [hidden, setHidden] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current)
    chartRef.current = chart
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const runsWithRecommended = runs
      .map((run) => ({
        run,
        config: run.config_results.find((c) => c.name === run.recommended_config) ?? run.config_results[0],
      }))
      .filter((r) => r.config)

    chart.setOption({
      animationDuration: 400,
      grid: { left: 36, right: 16, top: 16, bottom: 28 },
      xAxis: {
        type: 'category',
        data: runsWithRecommended.map((_, i) => `Run ${i + 1}`),
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.2)' } },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 1,
        splitLine: { show: false },
        axisLine: { show: false },
        axisLabel: { color: 'rgba(255,255,255,0.5)' },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#23204f',
        borderColor: 'rgba(140,130,255,0.25)',
        textStyle: { color: '#ffffff' },
      },
      series: SERIES_DEFS.filter((s) => !hidden.has(s.key)).map((s) => ({
        name: s.label,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: true,
        lineStyle: { color: s.color, width: 2 },
        itemStyle: { color: s.color },
        data: runsWithRecommended.map((r) => r.config!.retrieval_metrics[s.key] ?? r.config!.faithfulness ?? 0),
      })),
    })
  }, [runs, hidden])

  if (runs.length === 0) {
    return (
      <div className="flex h-56 flex-col items-center justify-center gap-1 text-center" style={{ color: 'var(--ev-muted)' }}>
        <p className="text-sm">No benchmark runs yet</p>
        <p className="text-xs">Run a benchmark to see retrieval quality trend over time.</p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div className="flex flex-wrap items-center gap-3" data-testid="retrieval-chart-legend">
          {SERIES_DEFS.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() =>
                setHidden((prev) => {
                  const next = new Set(prev)
                  if (next.has(s.key)) next.delete(s.key)
                  else next.add(s.key)
                  return next
                })
              }
              className="flex items-center gap-1.5 text-[11px]"
              style={{ color: hidden.has(s.key) ? 'var(--ev-muted)' : 'var(--ev-text)', opacity: hidden.has(s.key) ? 0.4 : 1 }}
            >
              <span className="size-2 rounded-full" style={{ background: s.color }} />
              {s.label}
            </button>
          ))}
        </div>
        <button type="button" aria-label="Chart settings" style={{ color: 'var(--ev-muted)' }}>
          <Settings className="size-3.5" />
        </button>
      </div>
      <div ref={containerRef} className="h-56 w-full" role="img" aria-label="Retrieval quality by run" />
    </div>
  )
}
