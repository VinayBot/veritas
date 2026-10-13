import type { ReactNode } from 'react'

export interface EvalKpiCardProps {
  label: string
  value: ReactNode
  /** Delta vs the previous real run — omit (not "0.0") when there is no previous run (G1: a
   * dash, never a fabricated zero). */
  delta?: { direction: 'up' | 'down'; label: string } | null
  icon?: ReactNode
  emptyDescription?: string
}

/** EV-3's KPI tile. Uses .theme-eval tokens directly (not the shared StatCard) — this surface
 * is always dark regardless of the global theme (G7), and StatCard's text-foreground etc.
 * would flip with it. */
export function EvalKpiCard({ label, value, delta, icon, emptyDescription }: EvalKpiCardProps) {
  return (
    <div
      className="theme-eval relative overflow-hidden rounded-2xl border p-4"
      style={{
        background: 'linear-gradient(180deg, var(--ev-bg-from), var(--ev-bg-to))',
        borderColor: 'var(--ev-border)',
      }}
      data-testid="eval-kpi-card"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium" style={{ color: 'var(--ev-muted)' }}>
          {label}
        </span>
        {icon && <span style={{ color: 'var(--ev-value)' }}>{icon}</span>}
      </div>
      {value === null || value === undefined ? (
        <p className="text-xs" style={{ color: 'var(--ev-muted)' }}>
          {emptyDescription ?? 'No data yet'}
        </p>
      ) : (
        <>
          <p className="font-display text-2xl font-semibold tabular-nums" style={{ color: 'var(--ev-value)' }}>
            {value}
          </p>
          <p className="mt-1 text-xs tabular-nums" style={{ color: 'var(--ev-muted)' }}>
            {delta ? (
              <span style={{ color: delta.direction === 'up' ? '#4ade80' : '#f87171' }}>
                {delta.direction === 'up' ? '↑' : '↓'} {delta.label}
              </span>
            ) : (
              '— no previous run'
            )}
          </p>
        </>
      )}
    </div>
  )
}
