import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { useReducedMotion } from 'framer-motion'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, RadarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { cn } from '@/lib/utils'

echarts.use([BarChart, LineChart, PieChart, RadarChart, GridComponent, LegendComponent, RadarComponent, TooltipComponent, CanvasRenderer])

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
  useLayoutEffect(() => {
    clickRef.current = onPointClick
  })

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
