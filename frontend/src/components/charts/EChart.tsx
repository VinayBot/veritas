import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useReducedMotion } from 'framer-motion'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, RadarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'

echarts.use([BarChart, LineChart, PieChart, RadarChart, GridComponent, LegendComponent, RadarComponent, TooltipComponent, CanvasRenderer])

/** Colours for a chart, read from the design tokens so canvas drawing follows the theme. */
export interface ChartTheme {
  series: string[]
  foreground: string
  muted: string
  border: string
  surface: string
  accent: string
  gold: string
  live: string
  success: string
  warning: string
  danger: string
}

const token = (style: CSSStyleDeclaration, name: string) => style.getPropertyValue(name).trim()

function readTheme(): ChartTheme {
  const style = getComputedStyle(document.documentElement)
  return {
    series: [1, 2, 3, 4, 5, 6].map((i) => token(style, `--color-chart-${i}`)),
    foreground: token(style, '--color-foreground'),
    muted: token(style, '--color-muted'),
    border: token(style, '--color-border'),
    surface: token(style, '--color-surface-raised'),
    accent: token(style, '--color-accent'),
    gold: token(style, '--color-gold'),
    live: token(style, '--color-live'),
    success: token(style, '--color-success'),
    warning: token(style, '--color-warning'),
    danger: token(style, '--color-danger'),
  }
}

export function useChartTheme(): ChartTheme {
  const { theme } = useTheme()
  // eslint-disable-next-line react-hooks/exhaustive-deps -- re-read the tokens when the theme flips
  return useMemo(readTheme, [theme])
}

/** Axis, tooltip and legend styling every chart shares. */
export function baseOption(t: ChartTheme): EChartsCoreOption {
  return {
    textStyle: { fontFamily: 'Inter, system-ui, sans-serif', color: t.muted },
    tooltip: {
      backgroundColor: t.surface,
      borderColor: t.border,
      textStyle: { color: t.foreground, fontSize: 12 },
      extraCssText: 'border-radius:10px;box-shadow:0 12px 32px -12px rgb(0 0 0 / 0.55);',
    },
    legend: { textStyle: { color: t.muted, fontSize: 11 }, icon: 'circle', itemWidth: 8, itemHeight: 8 },
  }
}

export const axisStyle = (t: ChartTheme) => ({
  axisLine: { lineStyle: { color: t.border } },
  axisTick: { show: false },
  axisLabel: { color: t.muted, fontSize: 11 },
  splitLine: { lineStyle: { color: t.border, opacity: 0.45, type: 'dashed' as const } },
})

/**
 * One ECharts canvas. The chart animates in when it first scrolls into view, respects reduced
 * motion, and always ships a real table of the same numbers for screen readers and for anyone
 * who would rather read than look ("View as table").
 */
export function EChart({
  option,
  label,
  table,
  height = 260,
  className,
  onPointClick,
  testId,
}: {
  option: EChartsCoreOption
  /** What the chart shows, read by screen readers. */
  label: string
  /** The same data as a table. */
  table?: ReactNode
  height?: number
  className?: string
  onPointClick?: (params: { name: string; seriesName?: string; dataIndex: number }) => void
  testId?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const reduced = useReducedMotion()
  const [visible, setVisible] = useState(false)
  const [showTable, setShowTable] = useState(false)
  const clickRef = useRef(onPointClick)
  clickRef.current = onPointClick

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const chart = echarts.init(el)
    chartRef.current = chart
    chart.on('click', (p) => clickRef.current?.({ name: String(p.name), seriesName: p.seriesName, dataIndex: p.dataIndex }))
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(el)
    const seen = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true)
          seen.disconnect()
        }
      },
      { threshold: 0.15 },
    )
    seen.observe(el)
    return () => {
      resize.disconnect()
      seen.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  // Nothing is drawn until the chart is on screen, so its entrance animation is actually seen.
  useEffect(() => {
    if (!visible) return
    chartRef.current?.setOption(
      { animation: !reduced, animationDuration: 700, animationEasing: 'cubicOut', animationDurationUpdate: 320, ...option },
      { notMerge: true },
    )
  }, [option, visible, reduced])

  return (
    <div className={cn('flex flex-col gap-2', className)} data-testid={testId}>
      <div ref={ref} role="img" aria-label={label} style={{ height }} className={cn('w-full', showTable && 'hidden')} />
      {table && (
        <>
          {showTable && <div className="overflow-x-auto">{table}</div>}
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            aria-pressed={showTable}
            className="self-end text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            {showTable ? 'View as chart' : 'View as table'}
          </button>
        </>
      )}
    </div>
  )
}

/** A plain table used as the non-visual version of a chart. */
export function ChartTable({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number | undefined)[][] }) {
  return (
    <table className="w-full text-left text-xs">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="text-muted-foreground">
          {head.map((h) => (
            <th key={h} scope="col" className="py-1.5 pr-4 font-medium">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} className="border-t border-border">
            {row.map((cell, j) => (
              <td key={j} className="py-1.5 pr-4 tabular-nums text-foreground">
                {cell ?? '—'}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
