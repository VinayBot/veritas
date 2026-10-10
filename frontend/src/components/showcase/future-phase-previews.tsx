import { useEffect, useRef, useState } from 'react'
import { ReactFlow, Background, Controls, type Node, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useTheme } from '@/lib/theme'

/**
 * These three tiles are deliberately NOT real screens — the Architecture tab
 * (@xyflow/react) and Knowledge Graph tab (react-force-graph-2d) are a later
 * phase someone else owns, and no chart screen exists yet either. This file
 * exists only to prove the three libraries the brief's STACK section
 * requires are actually installed and render without error on React 19,
 * each labelled as a placeholder rather than presented as a finished
 * feature — see the "Later phase" captions in ComponentShowcase.
 */

const FLOW_NODES: Node[] = [
  { id: '1', type: 'input', position: { x: 0, y: 40 }, data: { label: 'Ingest' } },
  { id: '2', position: { x: 170, y: 0 }, data: { label: 'Retrieve' } },
  { id: '3', position: { x: 170, y: 90 }, data: { label: 'Reason' } },
  { id: '4', type: 'output', position: { x: 340, y: 40 }, data: { label: 'Respond' } },
]

const FLOW_EDGES: Edge[] = [
  { id: 'e1-2', source: '1', target: '2' },
  { id: 'e1-3', source: '1', target: '3' },
  { id: 'e2-4', source: '2', target: '4' },
  { id: 'e3-4', source: '3', target: '4' },
]

/** @xyflow/react smoke test — intended real use: the Architecture tab. */
export function FlowPreview() {
  // @xyflow/react ships its own light-themed default node/control colors
  // regardless of the host page — colorMode is its own equivalent of our
  // .light convention, so this still follows the real theme toggle.
  const { theme } = useTheme()

  return (
    <div
      className="h-56 overflow-hidden rounded-[var(--radius-card)] border border-border"
      aria-label="Architecture graph placeholder (@xyflow/react smoke test, not a finished screen)"
    >
      <ReactFlow
        nodes={FLOW_NODES}
        edges={FLOW_EDGES}
        fitView
        colorMode={theme === 'light' ? 'light' : 'dark'}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

const GRAPH_DATA = {
  nodes: [{ id: 'doc' }, { id: 'entity-a' }, { id: 'entity-b' }, { id: 'entity-c' }],
  links: [
    { source: 'doc', target: 'entity-a' },
    { source: 'doc', target: 'entity-b' },
    { source: 'entity-a', target: 'entity-c' },
  ],
}

/** react-force-graph-2d smoke test — intended real use: the Knowledge Graph tab. */
export function GraphPreview() {
  const { theme } = useTheme()
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<ForceGraphMethods<object, object> | undefined>(undefined)
  const [size, setSize] = useState({ width: 320, height: 224 })
  const [accentColor, setAccentColor] = useState('#8b5cf6')

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Canvas fillStyle can't resolve CSS custom properties, so the accent hex
  // is read from the resolved style instead of hardcoded — keeps this in
  // sync with the real token if --color-accent is ever retuned, and across
  // the dark/light toggle.
  useEffect(() => {
    const resolved = getComputedStyle(document.documentElement)
      .getPropertyValue('--color-accent')
      .trim()
    if (resolved) setAccentColor(resolved)
  }, [theme])

  return (
    <div
      ref={containerRef}
      className="h-56 overflow-hidden rounded-[var(--radius-card)] border border-border"
      aria-label="Knowledge graph placeholder (react-force-graph-2d smoke test, not a finished screen)"
    >
      <ForceGraph2D
        ref={graphRef}
        graphData={GRAPH_DATA}
        width={size.width}
        height={size.height}
        backgroundColor="rgba(0,0,0,0)"
        nodeLabel="id"
        nodeColor={() => accentColor}
        linkColor={() => accentColor}
        linkWidth={1}
        nodeRelSize={5}
        cooldownTicks={100}
        onEngineStop={() => graphRef.current?.zoomToFit(400, 32)}
      />
    </div>
  )
}

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])
const SAMPLE_SERIES = [12, 18, 15, 24, 20, 30, 26]

/** ECharts smoke test — intended real use: later analytics/eval charts. */
export function ChartPreview() {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const { theme } = useTheme()

  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current)
    chartRef.current = chart
    const handleResize = () => chart.resize()
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--color-accent').trim()
    chart.setOption({
      animationDuration: 400,
      grid: { left: 8, right: 8, top: 8, bottom: 8 },
      xAxis: { type: 'category', show: false, data: SAMPLE_SERIES.map((_, i) => i) },
      yAxis: { type: 'value', show: false },
      tooltip: { trigger: 'axis' },
      series: [
        {
          type: 'line',
          data: SAMPLE_SERIES,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: accent, width: 2 },
          areaStyle: { color: accent, opacity: 0.12 },
        },
      ],
    })
  }, [theme])

  return (
    <div
      ref={containerRef}
      className="h-56 overflow-hidden rounded-[var(--radius-card)] border border-border"
      role="img"
      aria-label="Example line chart placeholder (ECharts smoke test, illustrative data)"
    />
  )
}
