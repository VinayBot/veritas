import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Activity, CircleCheck, CircleX, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { StatusDot } from '@/components/ui/status-dot'
import { STATUS_LABEL, type HealthStatus } from '@/components/ui/status-label'
import { Skeleton } from '@/components/ui/skeleton'
import { runSelfCheck } from '@/lib/api/client'
import type { SelfCheckResponse, Subsystem } from '@/lib/api/types'
import { ms, relativeTime } from '@/lib/format'
import type { SocketState } from '@/hooks/useTraceEvents'
import { cn } from '@/lib/utils'

/** The eight things the brief asks to be able to see at a glance, in this order. */
const STRIP_ORDER = ['ollama', 'chroma', 'bm25', 'graph_store', 'agent_graph', 'council', 'guardrails', 'trace_ws']

export interface TraceSocketInfo {
  state: SocketState
  watching: number
}

function socketStatus(info: TraceSocketInfo): { status: HealthStatus; detail: string } {
  if (info.watching === 0) return { status: 'unknown', detail: 'Nothing to watch yet: upload a document or ask a question.' }
  if (info.state === 'open') return { status: 'healthy', detail: `This browser is connected and watching ${info.watching} trace stream(s).` }
  if (info.state === 'connecting') return { status: 'degraded', detail: 'Connecting to the trace WebSocket…' }
  return { status: 'down', detail: 'This browser is not connected to the trace WebSocket. Nothing on the diagram will pulse until it reconnects.' }
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}

function Pill({ subsystem, override }: { subsystem: Subsystem; override?: { status: HealthStatus; detail: string } }) {
  useNow(5000) // keeps "checked 12s ago" honest between polls
  const status = (override?.status ?? subsystem.status) as HealthStatus
  const detail = override?.detail ?? subsystem.detail
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid={`health-pill-${subsystem.id}`}
          data-status={status}
          className={cn(
            'flex shrink-0 items-center gap-2 rounded-pill border bg-surface px-3 py-1.5 text-xs transition-colors duration-micro hover:bg-surface-raised',
            status === 'down' ? 'border-danger/60' : status === 'degraded' ? 'border-warning/50' : 'border-border',
          )}
        >
          <StatusDot status={status} />
          <span className="font-medium text-foreground">{subsystem.label}</span>
          <span className="tabular-nums text-muted-foreground">
            {subsystem.p50_latency_ms !== null ? `p50 ${ms(subsystem.p50_latency_ms)}` : '—'} · {relativeTime(subsystem.checked_at)}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-96" data-testid={`health-detail-${subsystem.id}`}>
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2">
            <span className="font-display text-sm font-semibold">{subsystem.label}</span>
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <StatusDot status={status} /> {STATUS_LABEL[status]}
            </span>
          </div>
          <p className="text-xs text-foreground">{detail}</p>
          {subsystem.error && (
            <div className="rounded-lg border border-danger/40 bg-danger/10 p-2">
              <p className="mb-1 text-[11px] font-medium text-danger">Exact error</p>
              <code className="block font-mono text-[11px] break-words whitespace-pre-wrap text-foreground">{subsystem.error}</code>
            </div>
          )}
          {subsystem.fix && <p className="text-xs text-muted-foreground">Fix: <span className="text-foreground">{subsystem.fix}</span></p>}
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            <dt>Check type</dt>
            <dd className="text-right text-foreground">{subsystem.kind}</dd>
            <dt>This check took</dt>
            <dd className="text-right tabular-nums text-foreground">{ms(subsystem.latency_ms)}</dd>
            <dt>Median check time</dt>
            <dd className="text-right tabular-nums text-foreground">{ms(subsystem.p50_latency_ms) ?? '—'}</dd>
            <dt>Last checked</dt>
            <dd className="text-right text-foreground">{new Date(subsystem.checked_at).toLocaleTimeString()}</dd>
          </dl>
          <details>
            <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground">Raw probe result</summary>
            <pre className="mt-2 max-h-56 overflow-auto rounded-lg bg-surface-raised p-2 font-mono text-[10px] text-foreground" data-lenis-prevent>
              {JSON.stringify(subsystem.raw, null, 2)}
            </pre>
          </details>
        </div>
      </PopoverContent>
    </Popover>
  )
}

export function HealthStrip({
  subsystems,
  error,
  traceSocket,
  onChecked,
}: {
  subsystems: Subsystem[] | null
  error: unknown
  traceSocket: TraceSocketInfo
  onChecked: () => void
}) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<SelfCheckResponse | null>(null)

  async function handleSelfCheck() {
    setRunning(true)
    try {
      const data = await runSelfCheck()
      setResult(data)
      onChecked()
      if (data.ok) toast.success(`Self-check passed in ${ms(data.total_ms)}`)
      else toast.error(`Self-check failed at: ${data.stages.filter((s) => !s.ok).map((s) => s.label).join(', ')}`)
    } catch (err) {
      toast.error(err instanceof Error ? `Self-check could not run: ${err.message}` : 'Self-check could not run')
    } finally {
      setRunning(false)
    }
  }

  // Lets the command palette trigger the same action, always with the current handler.
  const selfCheckRef = useRef(handleSelfCheck)
  useLayoutEffect(() => {
    selfCheckRef.current = handleSelfCheck
  })
  useEffect(() => {
    const handler = () => void selfCheckRef.current()
    window.addEventListener('veritas:self-check', handler)
    return () => window.removeEventListener('veritas:self-check', handler)
  }, [])

  const ordered = STRIP_ORDER.map((id) => subsystems?.find((s) => s.id === id)).filter((s): s is Subsystem => !!s)

  return (
    <section aria-label="System health" className="flex flex-col gap-3" data-testid="health-strip">
      <div className="flex items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          {error !== null && subsystems === null ? (
            <span className="flex items-center gap-2 rounded-pill border border-danger/60 bg-danger/10 px-3 py-1.5 text-xs text-danger" role="alert">
              <StatusDot status="down" /> The backend is unreachable — health cannot be checked. Start it with `make backend-dev`.
            </span>
          ) : subsystems === null ? (
            STRIP_ORDER.map((id) => <Skeleton key={id} className="h-8 w-40 shrink-0 rounded-pill" />)
          ) : (
            ordered.map((s) => <Pill key={s.id} subsystem={s} override={s.id === 'trace_ws' ? socketStatus(traceSocket) : undefined} />)
          )}
        </div>
        <Button size="sm" onClick={() => void handleSelfCheck()} disabled={running} data-testid="run-self-check">
          {running ? <Loader2 className="size-3.5 animate-spin" /> : <Activity className="size-3.5" />}
          {running ? 'Checking…' : 'Run self-check'}
        </Button>
      </div>

      {result && (
        <div className="rounded-xl border border-border bg-surface p-3" data-testid="self-check-result" data-ok={result.ok}>
          <div className="mb-2 flex items-center justify-between gap-2 text-xs">
            <span className="font-medium text-foreground">
              Self-check {result.ok ? 'passed' : 'failed'} · {ms(result.total_ms)} total · {new Date(result.ran_at).toLocaleTimeString()}
            </span>
            <button type="button" className="text-muted-foreground hover:text-foreground" onClick={() => setResult(null)}>
              Dismiss
            </button>
          </div>
          <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {result.stages.map((stage) => (
              <li key={stage.name} className={cn('rounded-lg border p-2 text-xs', stage.ok ? 'border-border' : 'border-danger/50 bg-danger/10')} data-testid={`self-check-${stage.name}`} data-ok={stage.ok}>
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 font-medium text-foreground">
                    {stage.ok ? <CircleCheck className="size-3.5 text-success" /> : <CircleX className="size-3.5 text-danger" />}
                    {stage.label}
                  </span>
                  <span className="tabular-nums text-muted-foreground">{ms(stage.duration_ms)}</span>
                </div>
                <p className="mt-1 break-words text-muted-foreground">{stage.error ?? stage.detail}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  )
}
