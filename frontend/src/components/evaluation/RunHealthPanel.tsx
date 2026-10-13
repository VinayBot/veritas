import type { BenchmarkRunResponse } from '@/lib/api/types'

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) {
    return <p className="text-[11px]" style={{ color: 'var(--ev-muted)' }}>Not enough runs yet for a trend</p>
  }
  const w = 160
  const h = 32
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w
    const y = h - ((v - min) / range) * h
    return `${x},${y}`
  })
  return (
    <svg width={w} height={h} role="img" aria-label="Latency trend sparkline">
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  )
}

export interface RunHealthPanelProps {
  runs: BenchmarkRunResponse[]
}

/** EV-6 bottom panel: p50/p95 latency, last benchmark gate status, a real sparkline — from
 * the recommended config of each real run, same convention as the chart above. */
export function RunHealthPanel({ runs }: RunHealthPanelProps) {
  if (runs.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1 text-center" style={{ color: 'var(--ev-muted)' }}>
        <p className="text-sm">No run health yet</p>
        <p className="text-xs">Run a benchmark to see latency and gate status.</p>
      </div>
    )
  }

  const latest = runs[runs.length - 1]
  const latestConfig = latest.config_results.find((c) => c.name === latest.recommended_config) ?? latest.config_results[0]
  const p50History = runs.map((r) => {
    const c = r.config_results.find((cc) => cc.name === r.recommended_config) ?? r.config_results[0]
    return c?.p50_latency_ms ?? 0
  })

  return (
    <div className="flex h-full flex-col gap-3">
      <h3 className="text-sm font-semibold" style={{ color: 'var(--ev-text)' }}>
        Run health
      </h3>
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div>
          <p style={{ color: 'var(--ev-muted)' }}>p50 latency</p>
          <p className="font-display text-lg font-semibold tabular-nums" style={{ color: 'var(--ev-value)' }}>
            {latestConfig ? `${Math.round(latestConfig.p50_latency_ms)}ms` : '—'}
          </p>
        </div>
        <div>
          <p style={{ color: 'var(--ev-muted)' }}>p95 latency</p>
          <p className="font-display text-lg font-semibold tabular-nums" style={{ color: 'var(--ev-value)' }}>
            {latestConfig ? `${Math.round(latestConfig.p95_latency_ms)}ms` : '—'}
          </p>
        </div>
      </div>
      <div>
        <p className="mb-1 text-xs" style={{ color: 'var(--ev-muted)' }}>
          Last gate status
        </p>
        <span
          className="inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium"
          style={
            latestConfig?.passes_hard_gates
              ? { color: 'var(--ev-high)', background: 'var(--ev-high-bg)', borderColor: 'rgba(74,222,128,0.4)' }
              : { color: '#f87171', background: 'rgba(248,113,113,0.15)', borderColor: 'rgba(248,113,113,0.4)' }
          }
        >
          {latestConfig?.passes_hard_gates ? 'pass' : 'fail'}
        </span>
      </div>
      <div>
        <p className="mb-1 text-xs" style={{ color: 'var(--ev-muted)' }}>
          p50 latency trend
        </p>
        <Sparkline values={p50History} color="var(--ev-fill)" />
      </div>
    </div>
  )
}
