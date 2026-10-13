import type { CandidateResultOut } from '@/lib/api/types'

export interface ChunkingStrategyRow {
  strategy: string
  chunks: number
  score: number
  queriesEvaluated: number
  ndcgAt5: number
}

const SCORE_THRESHOLD_HIGH = 0.8
const SCORE_THRESHOLD_MEDIUM = 0.6

function scoreBadge(score: number): { label: 'High' | 'Medium' | 'Low'; color: string; bg: string; border: string } {
  if (score >= SCORE_THRESHOLD_HIGH) return { label: 'High', color: 'var(--ev-high)', bg: 'var(--ev-high-bg)', border: 'rgba(74,222,128,0.4)' }
  if (score >= SCORE_THRESHOLD_MEDIUM) return { label: 'Medium', color: 'var(--ev-medium)', bg: 'var(--ev-medium-bg)', border: 'rgba(245,165,36,0.4)' }
  return { label: 'Low', color: '#f87171', bg: 'rgba(248,113,113,0.15)', border: 'rgba(248,113,113,0.4)' }
}

/** Groups the real persisted tournament candidates by chunking_strategy, keeping the
 * best-composite-score candidate per strategy — exactly one row per real strategy (up to 6,
 * see backend/app/chunking/registry.py), not an arbitrary or duplicated pick. */
export function candidatesToStrategyRows(candidates: CandidateResultOut[]): ChunkingStrategyRow[] {
  const bestByStrategy = new Map<string, CandidateResultOut>()
  for (const c of candidates) {
    const existing = bestByStrategy.get(c.chunking_strategy)
    if (!existing || c.composite_score > existing.composite_score) {
      bestByStrategy.set(c.chunking_strategy, c)
    }
  }
  return [...bestByStrategy.values()]
    .map((c) => ({
      strategy: c.chunking_strategy,
      chunks: c.index_size,
      score: c.composite_score,
      queriesEvaluated: c.n_samples,
      ndcgAt5: c.retrieval_metrics.ndcg_at_5 ?? 0,
    }))
    .sort((a, b) => b.score - a.score)
}

export function ChunkingStrategyTable({ rows }: { rows: ChunkingStrategyRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-1 text-center" style={{ color: 'var(--ev-muted)' }}>
        <p className="text-sm">No chunking comparison yet</p>
        <p className="text-xs">Run the Advisor to compare all 6 real chunking strategies.</p>
      </div>
    )
  }

  return (
    <div className="max-h-72 overflow-y-auto" data-testid="chunking-strategy-table">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0" style={{ background: 'var(--ev-bg-from)' }}>
          <tr style={{ color: 'var(--ev-muted)' }}>
            <th className="py-2 pr-3 font-medium">Strategy</th>
            <th className="py-2 pr-3 font-medium">Chunks</th>
            <th className="py-2 pr-3 font-medium">Score</th>
            <th className="py-2 pr-3 font-medium">Queries evaluated</th>
            <th className="py-2 font-medium">nDCG@5</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const badge = scoreBadge(row.score)
            return (
              <tr key={row.strategy} className="border-t" style={{ borderColor: 'var(--ev-border)' }}>
                <td className="py-2 pr-3 font-medium" style={{ color: 'var(--ev-text)' }}>
                  {row.strategy}
                </td>
                <td className="py-2 pr-3 tabular-nums" style={{ color: 'var(--ev-text)' }}>
                  {row.chunks}
                </td>
                <td className="py-2 pr-3">
                  <span
                    className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium"
                    style={{ color: badge.color, background: badge.bg, borderColor: badge.border }}
                  >
                    {row.score.toFixed(2)} &middot; {badge.label}
                  </span>
                </td>
                <td className="py-2 pr-3 tabular-nums" style={{ color: 'var(--ev-text)' }}>
                  {row.queriesEvaluated}
                </td>
                <td className="py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-20 overflow-hidden rounded-full" style={{ background: 'var(--ev-track)' }}>
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${Math.round(row.ndcgAt5 * 100)}%`, background: 'var(--ev-fill)' }}
                      />
                    </div>
                    <span className="tabular-nums" style={{ color: 'var(--ev-muted)' }}>
                      {Math.round(row.ndcgAt5 * 100)}%
                    </span>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
