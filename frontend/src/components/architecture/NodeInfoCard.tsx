import type { CSSProperties } from 'react'
import { X } from 'lucide-react'

export interface NodeInfoCardData {
  id: string
  label: string
  purpose: string
  modulePath: string
  status: string
  durationsMs: number[]
  lastEventAt: string | null
  planned: boolean
}

function percentile(sorted: number[], p: number): number {
  const idx = Math.min(sorted.length - 1, Math.floor(p * sorted.length))
  return sorted[idx]
}

// A plain, non-themed badge rather than the shared <Badge> — that component's "outline"
// variant reads `text-foreground`, which flips with the GLOBAL light/dark theme. This card's
// background is always dark (.theme-arch, G7), so under the global *light* theme that badge
// rendered near-black text on a near-black card — confirmed by screenshot, not guessed.
const STATUS_STYLE: Record<string, string> = {
  idle: 'border-white/25 text-white/70',
  queued: 'border-white/25 text-white/70',
  running: 'border-[#fbbf24]/50 bg-[#fbbf24]/15 text-[#fbbf24]',
  done: 'border-[#34d399]/50 bg-[#34d399]/15 text-[#34d399]',
  blocked: 'border-[#f87171]/50 bg-[#f87171]/15 text-[#f87171]',
  error: 'border-[#f87171]/50 bg-[#f87171]/15 text-[#f87171]',
  retrying: 'border-[#fbbf24]/50 bg-[#fbbf24]/15 text-[#fbbf24]',
}

/** AR-6: purpose, real module path, status, p50/p95 latency, last event time. p50/p95 are
 * computed from real durations observed THIS session (never fabricated) — with fewer than 2
 * samples, an honest "not enough data yet" instead of a number (G1). */
export function NodeInfoCard({
  data,
  pinned,
  onClose,
  style,
}: {
  data: NodeInfoCardData
  pinned: boolean
  onClose?: () => void
  style?: CSSProperties
}) {
  const sorted = [...data.durationsMs].sort((a, b) => a - b)
  const hasEnoughSamples = sorted.length >= 2
  const p50 = hasEnoughSamples ? percentile(sorted, 0.5) : sorted[0]
  const p95 = hasEnoughSamples ? percentile(sorted, 0.95) : null

  return (
    <div
      role="dialog"
      aria-label={`${data.label} details`}
      data-testid="architecture-node-card"
      data-node-id={data.id}
      className="theme-arch pointer-events-auto absolute z-20 w-64 rounded-lg border border-[color:var(--arch-border)] bg-[color:var(--arch-surface)] p-3 text-xs shadow-xl"
      style={style}
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <h3 className="font-semibold text-white">{data.label}</h3>
        <div className="flex items-center gap-1.5">
          <span
            className={`inline-flex h-5 items-center rounded-full border px-2 text-[11px] font-medium ${STATUS_STYLE[data.status] ?? STATUS_STYLE.idle}`}
          >
            {data.status}
          </span>
          {pinned && onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded p-0.5 text-white/50 hover:bg-white/10 hover:text-white"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
      </div>
      <p className="mb-2 text-white/70">{data.purpose}</p>
      {data.planned ? (
        <p className="rounded bg-white/5 px-2 py-1 text-[11px] text-white/50">
          Planned — not backed by real code yet.
        </p>
      ) : (
        <>
          <p className="font-mono text-[11px] text-white/50">{data.modulePath}</p>
          <dl className="mt-2 grid grid-cols-2 gap-1.5 text-[11px]">
            <div>
              <dt className="text-white/40">p50 latency</dt>
              <dd className="text-white">{sorted.length > 0 ? `${p50.toFixed(0)}ms` : 'no data yet'}</dd>
            </div>
            <div>
              <dt className="text-white/40">p95 latency</dt>
              <dd className="text-white">{p95 !== null ? `${p95.toFixed(0)}ms` : 'not enough data yet'}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-white/40">Last event</dt>
              <dd className="text-white">
                {data.lastEventAt ? new Date(data.lastEventAt).toLocaleTimeString() : 'none this session'}
              </dd>
            </div>
          </dl>
        </>
      )}
    </div>
  )
}
