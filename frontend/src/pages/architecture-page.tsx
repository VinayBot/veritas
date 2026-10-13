import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { useAppStore } from '@/store/app-store'
import { useTraceEvents } from '@/hooks/useTraceEvents'
import { StateMessage } from '@/components/ui/state-message'
import { SystemDesignView } from '@/components/architecture/SystemDesignView'
import { useArchitectureTopology } from '@/components/architecture/useArchitectureTopology'
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
} from '@/components/ui/drawer'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { getAudit } from '@/lib/api/client'
import type { AuditEntry, TraceEvent } from '@/lib/api/types'

const DetailedSwimlaneView = lazy(() =>
  import('@/components/architecture/DetailedSwimlaneView').then((m) => ({
    default: m.DetailedSwimlaneView,
  })),
)

const DECISION_VARIANT: Record<string, 'success' | 'destructive' | 'outline' | 'warning'> = {
  allow: 'success',
  block: 'destructive',
  redact: 'warning',
  escalate: 'warning',
}

export function ArchitecturePage() {
  const { documentId, sessionId } = useAppStore()
  const [source, setSource] = useState<'ingestion' | 'chat'>('ingestion')
  const [viewMode, setViewMode] = useState<'system' | 'detailed'>('system')
  const traceSessionId = source === 'ingestion' ? documentId : sessionId
  const { events, connected } = useTraceEvents(traceSessionId)
  const { topology } = useArchitectureTopology()
  // System Design spans the whole ingest -> query lifecycle, so unlike Detailed (which only
  // ever shows one lane) it needs both event streams at once regardless of which `source`
  // toggle Detailed has selected.
  const { events: ingestionEvents, connected: ingestionConnected } = useTraceEvents(
    viewMode === 'system' ? documentId : null,
  )
  const { events: chatEvents, connected: chatConnected } = useTraceEvents(
    viewMode === 'system' ? sessionId : null,
  )
  const systemDesignEvents = useMemo(
    () => [...ingestionEvents, ...chatEvents].sort((a, b) => a.seq - b.seq),
    [ingestionEvents, chatEvents],
  )
  const [selected, setSelected] = useState<{ stage: string; event: TraceEvent | null } | null>(
    null,
  )
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([])
  const [auditLoaded, setAuditLoaded] = useState(false)

  const loadAuditForSelection = useCallback(async (event: TraceEvent | null) => {
    if (!event) {
      setAuditEntries([])
      setAuditLoaded(true)
      return
    }
    setAuditLoaded(false)
    try {
      // Every guardrail check records its audit entry with the same trace_id as the stage
      // that ran it (app/agents/guardian.py, app/guardrails/retrieval.py all pass h.trace_id
      // straight through) — so filtering by it, not just session_id, gets exactly this node's
      // own decisions instead of every guardrail decision made anywhere in the session.
      const data = await getAudit({ session_id: event.session_id, limit: 100 })
      setAuditEntries(data.entries.filter((e) => e.trace_id === event.trace_id))
    } catch {
      setAuditEntries([])
    } finally {
      setAuditLoaded(true)
    }
  }, [])

  useEffect(() => {
    void loadAuditForSelection(selected?.event ?? null)
  }, [selected, loadAuditForSelection])

  if (!documentId) {
    return (
      <div className="flex h-screen items-center justify-center p-6">
        <StateMessage status="empty" description="Upload a document in Workspace first." />
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col gap-4 p-6">
      <header className="flex items-center justify-between gap-2">
        <div>
          <h1 className="font-display text-2xl font-semibold text-foreground">Architecture</h1>
          <p className="text-sm text-muted-foreground">
            Every pulse here is a real event from{' '}
            <code className="text-xs">/ws/trace/{traceSessionId ?? '...'}</code> — nothing is
            timer-driven.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {viewMode === 'detailed' && (
            <Badge variant={connected ? 'success' : 'outline'}>
              {connected ? 'live' : 'disconnected'}
            </Badge>
          )}
          <div className="flex gap-1 rounded-full bg-surface-raised p-1">
            {(['system', 'detailed'] as const).map((v) => (
              <button
                key={v}
                onClick={() => setViewMode(v)}
                data-testid={`view-mode-${v}`}
                className={cn(
                  'rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors',
                  viewMode === v ? 'bg-accent text-on-accent' : 'text-muted-foreground',
                )}
              >
                {v === 'system' ? 'System Design' : v}
              </button>
            ))}
          </div>
          {viewMode === 'detailed' && (
            <div className="flex gap-1 rounded-full bg-surface-raised p-1">
              {(['ingestion', 'chat'] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setSource(s)}
                  className={cn(
                    'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                    source === s ? 'bg-accent text-on-accent' : 'text-muted-foreground',
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </header>

      {viewMode === 'system' && (
        <div className="flex-1">
          <SystemDesignView
            topology={topology}
            events={systemDesignEvents}
            connected={ingestionConnected || chatConnected}
          />
        </div>
      )}

      {viewMode === 'detailed' && source === 'chat' && !sessionId && (
        <StateMessage
          status="empty"
          description="Send a chat message in Workspace first to see the agentic pipeline run."
        />
      )}

      {viewMode === 'detailed' && (
        <div className="flex-1 rounded-lg border border-border bg-surface">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Loading detailed view...
              </div>
            }
          >
            <DetailedSwimlaneView
              source={source}
              events={events}
              onSelectStage={(stage, event) => setSelected({ stage, event })}
            />
          </Suspense>
        </div>
      )}

      <Drawer open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DrawerContent>
          {selected && (
            <>
              <DrawerHeader>
                <DrawerTitle>{selected.stage}</DrawerTitle>
                <DrawerDescription>
                  {selected.event ? `status: ${selected.event.status}` : 'Not run yet'}
                </DrawerDescription>
              </DrawerHeader>
              {selected.event ? (
                <div className="flex flex-col gap-3 text-sm">
                  {selected.event.duration_ms !== null && (
                    <p className="text-muted-foreground">
                      Duration: {selected.event.duration_ms.toFixed(0)}ms
                    </p>
                  )}
                  {selected.event.output_preview && (
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Output</p>
                      <p className="rounded-md bg-surface-raised p-2 text-xs">
                        {selected.event.output_preview}
                      </p>
                    </div>
                  )}
                  {Object.keys(selected.event.metrics).length > 0 && (
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Metrics</p>
                      <pre className="overflow-x-auto rounded-md bg-surface-raised p-2 text-xs">
                        {JSON.stringify(selected.event.metrics, null, 2)}
                      </pre>
                    </div>
                  )}
                  <div data-testid="node-audit-entries">
                    <p className="mb-1 text-xs font-medium text-muted-foreground">
                      Guardrail Decisions
                    </p>
                    {!auditLoaded && (
                      <p className="text-xs text-muted-foreground">Loading...</p>
                    )}
                    {auditLoaded && auditEntries.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        No guardrail decisions recorded for this node.
                      </p>
                    )}
                    {auditLoaded && auditEntries.length > 0 && (
                      <div className="flex flex-col gap-2">
                        {auditEntries.map((entry) => (
                          <div
                            key={entry.id}
                            className="rounded-md border border-border bg-surface-raised p-2 text-xs"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-foreground">
                                {entry.layer} / {entry.rule}
                              </span>
                              <Badge variant={DECISION_VARIANT[entry.decision] ?? 'outline'}>
                                {entry.decision}
                              </Badge>
                            </div>
                            {entry.redacted_excerpt && (
                              <p className="mt-1 truncate text-muted-foreground">
                                {entry.redacted_excerpt}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No trace event for this stage yet in the current session.
                </p>
              )}
            </>
          )}
        </DrawerContent>
      </Drawer>
    </div>
  )
}
