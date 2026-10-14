import { useMemo } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import { useTheme } from '@/lib/theme-context'

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

