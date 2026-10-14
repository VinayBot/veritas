import { useEffect, useState } from 'react'
import { Copy, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '@/components/ui/drawer'
import { EmptyState, ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { MetricTip } from '@/components/ui/metric-tip'
import { StatusDot } from '@/components/ui/status-dot'
import { STATUS_LABEL } from '@/components/ui/status-label'
import { getAudit, getNodeEvents } from '@/lib/api/client'
import type { ArchitectureNode, AuditEntry, TraceEvent } from '@/lib/api/types'
import { ms, relativeTime } from '@/lib/format'
import type { StageSummary } from './scene'

const PROBE_KIND: Record<string, string> = {
  dependency: 'An external dependency was contacted.',
  functional: 'The component was exercised directly.',
  config: 'Read from configuration.',
  trace: 'Inferred from its most recent real run.',
  import: 'The module imports cleanly. It has nothing external to probe, so this is the weakest kind of check.',
}

const EVENT_VARIANT: Record<string, 'success' | 'destructive' | 'outline' | 'warning'> = {
  done: 'success',
  error: 'destructive',
  blocked: 'warning',
  running: 'outline',
}

const DECISION_VARIANT: Record<string, 'success' | 'destructive' | 'outline' | 'warning'> = {
  allow: 'success',
  block: 'destructive',
  redact: 'warning',
  escalate: 'warning',
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      {children}
    </section>
  )
}

function ModuleDetail({ node, statsSince }: { node: ArchitectureNode; statsSince: string }) {
  const [events, setEvents] = useState<TraceEvent[] | null>(null)
  const [eventsError, setEventsError] = useState<unknown>(null)
  const [audit, setAudit] = useState<AuditEntry[] | null>(null)

  // Another node, or new activity on this one: drop what was shown before fetching again.
  const detailKey = `${node.id}:${node.invocation_count}`
  const [shownFor, setShownFor] = useState(detailKey)
  if (shownFor !== detailKey) {
    setShownFor(detailKey)
    setEvents(null)
    setEventsError(null)
    setAudit(null)
  }

  useEffect(() => {
    let cancelled = false
    getNodeEvents(node.id)
      .then(async (data) => {
        if (cancelled) return
        setEvents(data.events)
        // Guardrail checks record their audit entry under the trace id of the stage that ran
        // them, so the latest event of a guardian node leads straight to its decisions.
        const latest = data.events[0]
        if (latest && node.trace_stages.some((s) => s.startsWith('guardian') || s === 'retriever')) {
          const log = await getAudit({ session_id: latest.session_id, limit: 100 })
          if (!cancelled) setAudit(log.entries.filter((e) => e.trace_id === latest.trace_id))
        }
      })
      .catch((err) => !cancelled && setEventsError(err))
    return () => {
      cancelled = true
    }
  }, [node.id, node.trace_stages, node.invocation_count])

  async function copyPath() {
    try {
      await navigator.clipboard.writeText(node.source_path)
      toast.success('Path copied')
    } catch {
      toast.error('Could not copy to the clipboard')
    }
  }

  const config = Object.entries(node.config)
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto pr-1" data-lenis-prevent>
      <Section title="Status">
        <div className="flex items-center gap-2 text-sm">
          <StatusDot status={node.status} />
          <span className="font-medium text-foreground">{STATUS_LABEL[node.status]}</span>
        </div>
        <p className="text-xs text-foreground" data-testid="node-status-detail">{node.status_detail}</p>
        <p className="text-[11px] text-muted-foreground">{PROBE_KIND[node.probe_kind] ?? node.probe_kind}</p>
      </Section>

      <Section title="Latency">
        {node.latency_sample_size === 0 ? (
          <p className="text-xs text-muted-foreground">No runs recorded since the backend started ({relativeTime(statsSince)}).</p>
        ) : (
          <dl className="grid grid-cols-3 gap-2 text-center">
            {[
              { label: 'p50', term: 'p50' as const, value: node.p50_latency_ms },
              { label: 'p95', term: 'p95' as const, value: node.latency_sample_size >= 2 ? node.p95_latency_ms : null },
              { label: 'last', term: undefined, value: node.last_latency_ms },
            ].map((item) => (
              <div key={item.label} className="rounded-lg bg-surface-raised p-2">
                <dt className="text-[10px] text-muted-foreground">
                  <MetricTip term={item.term}>{item.label}</MetricTip>
                </dt>
                <dd className="font-display text-base font-semibold tabular-nums text-foreground">{ms(item.value) ?? '—'}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="text-[11px] text-muted-foreground">
          {node.invocation_count} run{node.invocation_count === 1 ? '' : 's'}
          {node.error_count > 0 && `, ${node.error_count} errored`} since the backend started. These figures are kept in memory and reset on restart.
        </p>
      </Section>

      <Section title="Configuration">
        {config.length === 0 ? (
          <p className="text-xs text-muted-foreground">This module has no settings to show.</p>
        ) : (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs" data-testid="node-config">
            {config.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-muted-foreground">{key.replace(/_/g, ' ')}</dt>
                <dd className="break-words text-right text-foreground">{Array.isArray(value) ? value.join(', ') : String(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </Section>

      <Section title="Last 10 trace events">
        {eventsError ? (
          <ErrorState error={eventsError} compact />
        ) : events === null ? (
          <LoadingState shape="lines" rows={4} label="Loading trace events" />
        ) : events.length === 0 ? (
          <EmptyState compact title="No events yet" description="This node has not run since the backend started." />
        ) : (
          <ol className="flex flex-col gap-1.5" data-testid="node-events">
            {events.map((event) => (
              <li key={`${event.session_id}-${event.seq}`} className="rounded-lg border border-border bg-surface-raised p-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5">
                    <Badge variant={EVENT_VARIANT[event.status] ?? 'outline'}>{event.status}</Badge>
                    <span className="font-medium text-foreground">{event.stage}</span>
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    {ms(event.duration_ms) ?? '—'} · {relativeTime(event.started_at)}
                  </span>
                </div>
                {event.output_preview && <p className="mt-1 line-clamp-2 break-words text-muted-foreground">{event.output_preview}</p>}
              </li>
            ))}
          </ol>
        )}
      </Section>

      {audit !== null && (
        <Section title="Guardrail decisions for its latest run">
          {audit.length === 0 ? (
            <p className="text-xs text-muted-foreground">No guardrail decision was recorded for that run.</p>
          ) : (
            <ul className="flex flex-col gap-1.5" data-testid="node-audit-entries">
              {audit.map((entry) => (
                <li key={entry.id} className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface-raised p-2 text-xs">
                  <span className="font-medium text-foreground">
                    {entry.layer} / {entry.rule}
                  </span>
                  <Badge variant={DECISION_VARIANT[entry.decision] ?? 'outline'}>{entry.decision}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      <Section title="Source">
        <code className="block rounded-lg bg-surface-raised p-2 font-mono text-[11px] break-all text-foreground" data-testid="node-source-path">
          {node.source_path}
        </code>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => void copyPath()}>
            <Copy className="size-3.5" /> Copy path
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href={`vscode://file/${node.source_abs_path}`}>
              <ExternalLink className="size-3.5" /> Open in editor
            </a>
          </Button>
        </div>
      </Section>
    </div>
  )
}

function StageDetail({ summary, onOpenModule }: { summary: StageSummary; onOpenModule: (id: string) => void }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1" data-lenis-prevent>
      <p className="text-sm text-muted-foreground">{summary.description}</p>
      <ul className="flex flex-col gap-1.5" data-testid="stage-modules">
        {summary.modules.map((module) => (
          <li key={module.id}>
            <button
              type="button"
              onClick={() => onOpenModule(module.id)}
              className="flex w-full items-start gap-2 rounded-lg border border-border bg-surface-raised p-2.5 text-left text-xs transition-colors duration-micro hover:border-accent/50"
            >
              <StatusDot status={module.status} className="mt-1" />
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-foreground">{module.label}</span>
                <span className="block text-muted-foreground">{module.one_line_purpose}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function NodeDrawer({
  node,
  summary,
  statsSince,
  onClose,
  onOpenModule,
}: {
  node: ArchitectureNode | null
  summary: StageSummary | null
  statsSince: string
  onClose: () => void
  onOpenModule: (id: string) => void
}) {
  const open = node !== null || summary !== null
  return (
    <Drawer open={open} onOpenChange={(next) => !next && onClose()}>
      <DrawerContent
        className="max-w-md"
        data-testid="node-drawer"
        // Focus the panel, not its first control: that control is a tooltip trigger, and
        // landing on it would pop a tooltip open and make the first Escape close that instead.
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          ;(event.currentTarget as HTMLElement).focus()
        }}
      >
        {node && (
          <>
            <DrawerHeader>
              <DrawerTitle>{node.label}</DrawerTitle>
              <DrawerDescription>{node.one_line_purpose}</DrawerDescription>
            </DrawerHeader>
            <ModuleDetail node={node} statsSince={statsSince} />
          </>
        )}
        {summary && !node && (
          <>
            <DrawerHeader>
              <DrawerTitle>
                {summary.stage !== null ? `${summary.stage}. ` : ''}
                {summary.label}
              </DrawerTitle>
              <DrawerDescription>{summary.modules.length} modules in this stage</DrawerDescription>
            </DrawerHeader>
            <StageDetail summary={summary} onOpenModule={onOpenModule} />
          </>
        )}
      </DrawerContent>
    </Drawer>
  )
}
