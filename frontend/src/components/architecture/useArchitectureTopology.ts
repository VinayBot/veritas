import { useEffect, useState } from 'react'
import { getArchitectureTopology } from '@/lib/api/client'
import type { ArchitectureTopologyResponse } from '@/lib/api/types'

interface TopologyState {
  topology: ArchitectureTopologyResponse | null
  loading: boolean
  error: string | null
}

/** Fetches the real system topology once (GET /api/v1/architecture/topology) — the backend's
 * own inventory of node ids / module paths / groups, checked against the hand-authored
 * frontend layout by the vitest contract test. No fallback/synthetic data on failure: an
 * honest error state instead (G1). */
export function useArchitectureTopology(): TopologyState {
  const [state, setState] = useState<TopologyState>({ topology: null, loading: true, error: null })

  useEffect(() => {
    let cancelled = false
    getArchitectureTopology()
      .then((topology) => {
        if (!cancelled) setState({ topology, loading: false, error: null })
      })
      .catch((err) => {
        if (!cancelled) {
          setState({
            topology: null,
            loading: false,
            error: err instanceof Error ? err.message : 'Failed to load architecture topology',
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return state
}
