import { memo, type KeyboardEvent, type ReactNode } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { motion, useReducedMotion } from 'framer-motion'
import { StatusDot } from '@/components/ui/status-dot'
import { STATUS_LABEL } from '@/components/ui/status-label'
import type { ArchitectureNode, NodeStatus } from '@/lib/api/types'
import { ms } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { StageSummary } from './scene'
import type { NodeActivity } from './trace'

export interface CanvasNodeData extends Record<string, unknown> {
  order: number
  dimmed: boolean
  activity: NodeActivity
  /** An error stays visible until the viewer clears it. */
  stickyError: boolean
  selected: boolean
  showConfig: boolean
  node?: ArchitectureNode
  summary?: StageSummary
  childCount?: number
  label?: string
  onSelect: (id: string) => void
  onHover: (id: string | null) => void
}

const STAGE_ACCENT: Record<number, string> = {
  1: 'bg-chart-2',
  2: 'bg-chart-3',
  3: 'bg-chart-1',
  4: 'bg-chart-4',
  5: 'bg-chart-5',
}

const ENTRANCE_STEP_S = 0.05

function HiddenHandles() {
  return (
    <>
      <Handle type="target" position={Position.Left} isConnectable={false} className="!pointer-events-none !opacity-0" />
      <Handle type="source" position={Position.Right} isConnectable={false} className="!pointer-events-none !opacity-0" />
    </>
  )
}

function statusFrame(status: NodeStatus | undefined): string {
  switch (status) {
    case 'down':
      return 'border-danger/70'
    case 'degraded':
      return 'border-warning/60'
    case 'not_configured':
      return 'border-dashed border-border opacity-70'
    case 'disabled':
      return 'border-border opacity-60'
    default:
      return 'border-border'
  }
}

/** Shared shell: entrance, hover dimming, the active bloom, the error ring and shake, and
 * keyboard activation. Only transform and opacity are ever animated. */
function NodeShell({
  id,
  data,
  ariaLabel,
  className,
  children,
}: {
  id: string
  data: CanvasNodeData
  ariaLabel: string
  className?: string
  children: ReactNode
}) {
  const reduced = useReducedMotion()
  const active = data.activity === 'active'
  const errored = data.stickyError || data.activity === 'error'

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      data.onSelect(id)
    }
  }

  return (
    <motion.div
      initial={reduced ? false : { opacity: 0, scale: 0.94, y: 8 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={reduced ? { duration: 0 } : { type: 'spring', stiffness: 260, damping: 26, delay: data.order * ENTRANCE_STEP_S }}
      className="h-full w-full"
    >
      <motion.div
        animate={errored && !reduced ? { x: [0, -5, 5, -3, 3, 0] } : { x: 0 }}
        transition={{ duration: 0.32 }}
        className="h-full w-full"
      >
        <div
          role="button"
          tabIndex={0}
          aria-label={ariaLabel}
          aria-pressed={data.selected}
          data-testid={`arch-node-${id}`}
          data-activity={data.activity}
          data-status={data.node?.status ?? data.summary?.worst}
          onClick={() => data.onSelect(id)}
          onKeyDown={onKeyDown}
          onMouseEnter={() => data.onHover(id)}
          onMouseLeave={() => data.onHover(null)}
          onFocus={() => data.onHover(id)}
          onBlur={() => data.onHover(null)}
          className={cn(
            // xyflow sets pointer-events:none on a node wrapper it considers non-interactive,
            // and that is inherited, so the card opts back in.
            'pointer-events-auto relative h-full w-full cursor-pointer rounded-xl border bg-surface-raised text-left outline-none',
            'transition-[opacity,transform] duration-[150ms] ease-out',
            'focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background',
            data.dimmed ? 'opacity-25' : 'opacity-100',
            active && 'scale-[1.02]',
            data.selected && 'ring-2 ring-accent',
            errored && 'ring-2 ring-danger',
            className,
          )}
        >
          {/* Bloom: a static glow whose opacity is the only thing that changes. */}
          <span
            aria-hidden="true"
            className={cn(
              'pointer-events-none absolute -inset-1 rounded-2xl bg-live/25 blur-md transition-opacity duration-standard ease-enter',
              active ? 'opacity-100' : 'opacity-0',
            )}
            style={active ? { willChange: 'opacity' } : undefined}
          />
          {active && !reduced && <span aria-hidden="true" className="node-ripple pointer-events-none absolute inset-0 rounded-xl border-2 border-live" />}
          <div className="relative h-full w-full">{children}</div>
        </div>
      </motion.div>
      <HiddenHandles />
    </motion.div>
  )
}

function describe(node: ArchitectureNode, activity: NodeActivity): string {
  return `${node.label}. ${STATUS_LABEL[node.status]}${activity === 'active' ? ', running now' : ''}. ${node.one_line_purpose}`
}

function configValue(value: unknown): string {
  if (Array.isArray(value)) return value.length > 2 ? `${value.slice(0, 2).join(', ')} +${value.length - 2}` : value.join(', ')
  if (value === null || value === undefined) return '—'
  return String(value)
}

export const ModuleNode = memo(function ModuleNode({ id, data }: NodeProps) {
  const d = data as CanvasNodeData
  const node = d.node!
  const config = d.showConfig ? Object.entries(node.config).slice(0, 3) : []
  return (
    <NodeShell id={id} data={d} ariaLabel={describe(node, d.activity)} className={statusFrame(node.status)}>
      <span aria-hidden="true" className={cn('absolute top-3 bottom-3 left-0 w-1 rounded-r-full', node.stage ? STAGE_ACCENT[node.stage] : 'bg-muted')} />
      <div className="flex h-full flex-col justify-between gap-1 py-2 pr-3 pl-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5">
            <StatusDot status={node.status} />
            <span className="truncate text-[13px] font-semibold text-foreground">{node.label}</span>
          </span>
          {node.invocation_count > 0 && (
            <span className="shrink-0 rounded-pill bg-surface px-1.5 py-0.5 text-[10px] tabular-nums text-muted-foreground" title="Runs since the backend started">
              ×{node.invocation_count}
            </span>
          )}
        </div>
        {config.length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-2 text-[10px] leading-4">
            {config.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-muted-foreground">{key.replace(/_/g, ' ')}</dt>
                <dd className="truncate text-right text-foreground" title={configValue(value)}>
                  {configValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        )}
        <div className="flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
          <code className="truncate font-mono">{node.module_path}</code>
          <span className="shrink-0 tabular-nums">{node.p50_latency_ms !== null ? `p50 ${ms(node.p50_latency_ms)}` : node.documented ? '' : 'undocumented'}</span>
        </div>
      </div>
    </NodeShell>
  )
})

export const ChildNode = memo(function ChildNode({ id, data }: NodeProps) {
  const d = data as CanvasNodeData
  const node = d.node!
  return (
    <NodeShell id={id} data={d} ariaLabel={describe(node, d.activity)} className={cn('bg-surface', statusFrame(node.status))}>
      <div className="flex h-full flex-col justify-center gap-0.5 px-2.5">
        <span className="flex min-w-0 items-center gap-1.5">
          <StatusDot status={node.status} />
          <span className="truncate text-xs font-semibold text-foreground">{node.label}</span>
        </span>
        <span className="truncate pl-3.5 text-[10px] tabular-nums text-muted-foreground">
          {node.invocation_count > 0 ? `×${node.invocation_count}${node.p50_latency_ms !== null ? ` · p50 ${ms(node.p50_latency_ms)}` : ''}` : 'no runs yet'}
        </span>
      </div>
    </NodeShell>
  )
})

export const GroupNode = memo(function GroupNode({ id, data }: NodeProps) {
  const d = data as CanvasNodeData
  const node = d.node!
  const reduced = useReducedMotion()
  return (
    <motion.div
      initial={reduced ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduced ? 0 : 0.32, delay: reduced ? 0 : d.order * ENTRANCE_STEP_S }}
      className={cn(
        'h-full w-full rounded-2xl border border-dashed border-accent/40 bg-accent/5 transition-opacity duration-[150ms] ease-out',
        d.dimmed ? 'opacity-25' : 'opacity-100',
      )}
    >
      <div
        role="button"
        tabIndex={0}
        aria-label={`${describe(node, d.activity)} Contains ${d.childCount ?? 0} nodes.`}
        data-testid={`arch-node-${id}`}
        data-status={node.status}
        onClick={() => d.onSelect(id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            d.onSelect(id)
          }
        }}
        onMouseEnter={() => d.onHover(id)}
        onMouseLeave={() => d.onHover(null)}
        onFocus={() => d.onHover(id)}
        onBlur={() => d.onHover(null)}
        className="pointer-events-auto flex h-10 cursor-pointer items-center gap-2 rounded-t-2xl px-4 outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <StatusDot status={node.status} />
        <span className="text-[13px] font-semibold text-foreground">{node.label}</span>
        <span className="text-[10px] text-muted-foreground">
          {d.childCount} nodes · edges read from the compiled graph
        </span>
      </div>
      <HiddenHandles />
    </motion.div>
  )
})

export const StageNode = memo(function StageNode({ id, data }: NodeProps) {
  const d = data as CanvasNodeData
  const summary = d.summary!
  const counts = summary.modules.reduce<Record<string, number>>((acc, m) => {
    acc[m.status] = (acc[m.status] ?? 0) + 1
    return acc
  }, {})
  const problems = (counts.down ?? 0) + (counts.degraded ?? 0)
  const topLevel = summary.modules.filter((m) => !m.parent)
  const nested = summary.modules.length - topLevel.length
  return (
    <NodeShell
      id={id}
      data={d}
      ariaLabel={`Stage ${summary.stage ?? ''}: ${summary.label}. ${topLevel.length} modules, ${problems} with problems. ${summary.description}`}
      className="border-border"
    >
      <span aria-hidden="true" className={cn('absolute inset-x-4 top-0 h-1 rounded-b-full', summary.stage ? STAGE_ACCENT[summary.stage] : 'bg-muted')} />
      <div className="flex h-full flex-col gap-2 p-4 pt-5">
        <div className="flex items-center justify-between gap-2">
          <span className="font-display text-base font-semibold text-foreground">
            {summary.stage !== null && <span className="mr-1.5 text-muted-foreground">{summary.stage}</span>}
            {summary.label}
          </span>
          <StatusDot status={summary.worst} />
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">{summary.description}</p>
        <ul className="mt-1 flex min-h-0 flex-1 flex-col gap-1 overflow-hidden text-[11px]">
          {topLevel.slice(0, 8)
            .map((m) => (
              <li key={m.id} className="flex items-center gap-1.5 text-foreground">
                <StatusDot status={m.status} />
                <span className="truncate">{m.label}</span>
              </li>
            ))}
        </ul>
        <div className="flex flex-wrap gap-1.5 text-[11px]">
          <span className="rounded-pill bg-surface px-2 py-0.5 text-foreground">
            {topLevel.length} modules{nested > 0 ? ` · ${nested} agent nodes` : ''}
          </span>
          {problems > 0 && <span className="rounded-pill bg-warning/15 px-2 py-0.5 text-warning">{problems} need attention</span>}
          {summary.invocations > 0 && (
            <span className="rounded-pill bg-surface px-2 py-0.5 tabular-nums text-muted-foreground" title="Runs since the backend started">
              ×{summary.invocations} runs
            </span>
          )}
        </div>
      </div>
    </NodeShell>
  )
})

export const LaneNode = memo(function LaneNode({ data }: NodeProps) {
  const d = data as { label: string; stage: number | null }
  return (
    <div className="pointer-events-none h-full w-full rounded-2xl border border-border/50 bg-surface/40">
      <div className="flex h-full w-[104px] flex-col justify-center gap-1 border-r border-border/50 px-3">
        {d.stage !== null && <span className="font-display text-2xl leading-none font-semibold text-muted-foreground/60">{d.stage}</span>}
        <span className="text-xs leading-tight font-medium text-muted-foreground">{d.label}</span>
      </div>
    </div>
  )
})
