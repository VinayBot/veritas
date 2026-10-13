import { Crosshair, Eraser, Plug, PlugZap, RotateCcw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import type { SocketState } from '@/hooks/useTraceEvents'
import type { TraceEvent } from '@/lib/api/types'
import { ms } from '@/lib/format'
import { cn } from '@/lib/utils'

const EVENT_VARIANT: Record<string, 'success' | 'destructive' | 'outline' | 'warning'> = {
  done: 'success',
  error: 'destructive',
  blocked: 'warning',
  running: 'outline',
  retrying: 'warning',
  queued: 'outline',
}

export interface TraceSource {
  label: string
  sessionId: string | null
  socket: SocketState
}

/** The Live Trace side panel: connection state per stream, controls, and the real events in
 * the order they arrived. It is also the non-animated record of everything the diagram
 * shows, so the view stays usable with motion reduced. */
export function TraceDock({
  sources,
  events,
  overall,
  follow,
  onToggleFollow,
  socketEnabled,
  onToggleSocket,
  replaying,
  onReplay,
  canReplay,
  onClearErrors,
  hasErrors,
  pulsesDrawn,
  stageToNode,
  onSelectNode,
}: {
  sources: TraceSource[]
  events: TraceEvent[]
  overall: 'live' | 'connecting' | 'disconnected' | 'idle' | 'replay'
  follow: boolean
  onToggleFollow: () => void
  socketEnabled: boolean
  onToggleSocket: () => void
  replaying: boolean
  onReplay: () => void
  canReplay: boolean
  onClearErrors: () => void
  hasErrors: boolean
  /** Packets drawn since the page loaded; each one stands for a real hop. */
  pulsesDrawn: number
  stageToNode: Record<string, string>
  onSelectNode: (nodeId: string) => void
}) {
  const latest = [...events].sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at) || b.seq - a.seq).slice(0, 40)
  const chip = {
    live: { variant: 'success' as const, text: 'live' },
    connecting: { variant: 'warning' as const, text: 'connecting' },
    disconnected: { variant: 'destructive' as const, text: 'disconnected' },
    idle: { variant: 'outline' as const, text: 'nothing to watch' },
    replay: { variant: 'warning' as const, text: 'replay of a recorded trace' },
  }[overall]

  return (
    <aside className="flex h-full w-80 shrink-0 flex-col gap-3 rounded-xl border border-border bg-surface p-4" aria-label="Live trace" data-testid="trace-dock">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-display text-sm font-semibold text-foreground">Live trace</h2>
        <Badge variant={chip.variant} data-testid="trace-status-chip" data-state={overall}>
          {chip.text}
        </Badge>
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Every pulse is a real event from <code>/ws/trace</code>. A packet leaves when the next stage actually starts, and its speed reflects how long the stage
        before it took, so the animation trails reality by its own length. If the socket is closed, nothing moves.
      </p>

      <ul className="flex flex-col gap-1 text-[11px]">
        {sources.map((source) => (
          <li key={source.label} className="flex items-center justify-between gap-2 rounded-lg bg-surface-raised px-2 py-1.5">
            <span className="text-muted-foreground">{source.label}</span>
            <span className="truncate font-mono text-foreground" title={source.sessionId ?? undefined}>
              {source.sessionId ? `${source.sessionId.slice(0, 8)} · ${source.socket}` : 'none yet'}
            </span>
          </li>
        ))}
      </ul>

      <p className="text-[11px] text-muted-foreground">
        <span className="font-medium tabular-nums text-foreground" data-testid="pulses-drawn">{pulsesDrawn}</span> pulse{pulsesDrawn === 1 ? '' : 's'} drawn,{' '}
        <span className="tabular-nums">{events.length}</span> events received.
      </p>

      <div className="flex flex-wrap gap-1.5">
        <Button size="xs" variant={follow ? 'default' : 'outline'} aria-pressed={follow} onClick={onToggleFollow} data-testid="follow-trace">
          <Crosshair className="size-3" /> Follow trace
        </Button>
        <Button size="xs" variant="outline" onClick={onToggleSocket} data-testid="toggle-trace-socket" aria-pressed={!socketEnabled}>
          {socketEnabled ? <Plug className="size-3" /> : <PlugZap className="size-3" />}
          {socketEnabled ? 'Disconnect' : 'Reconnect'}
        </Button>
        <Button size="xs" variant="outline" onClick={onReplay} disabled={!canReplay || replaying} data-testid="replay-trace">
          <RotateCcw className="size-3" /> {replaying ? 'Replaying…' : 'Replay'}
        </Button>
        {hasErrors && (
          <Button size="xs" variant="outline" onClick={onClearErrors} data-testid="clear-errors">
            <Eraser className="size-3" /> Clear errors
          </Button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto" data-lenis-prevent role="log" aria-label="Trace events, newest first" data-testid="trace-events">
        {latest.length === 0 ? (
          <EmptyState
            compact
            title="No events yet"
            description="Upload a document or ask a question in Workspace, then watch it move through the system here."
          />
        ) : (
          <ol className="flex flex-col gap-1">
            {latest.map((event) => {
              const nodeId = stageToNode[event.stage]
              return (
                <li key={`${event.session_id}-${event.seq}`}>
                  <button
                    type="button"
                    disabled={!nodeId}
                    onClick={() => nodeId && onSelectNode(nodeId)}
                    className={cn(
                      'flex w-full items-center justify-between gap-2 rounded-lg border border-transparent px-2 py-1.5 text-left text-xs transition-colors duration-micro',
                      nodeId && 'hover:border-border hover:bg-surface-raised',
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-1.5">
                      <Badge variant={EVENT_VARIANT[event.status] ?? 'outline'}>{event.status}</Badge>
                      <span className="truncate font-medium text-foreground">{event.stage}</span>
                    </span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">{ms(event.duration_ms) ?? '…'}</span>
                  </button>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </aside>
  )
}
