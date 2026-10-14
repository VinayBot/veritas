import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

interface PollingState<T> {
  data: T | null
  error: unknown
  /** Milliseconds since epoch of the last successful fetch. */
  updatedAt: number | null
  loading: boolean
  refresh: () => void
}

/**
 * Polls `fetcher` on an interval, backing off exponentially (up to `maxIntervalMs`) while it
 * keeps failing so a dead backend is not hammered, and returning to the base interval on the
 * first success. Pauses while the tab is hidden.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  { intervalMs = 15_000, maxIntervalMs = 120_000, enabled = true }: { intervalMs?: number; maxIntervalMs?: number; enabled?: boolean } = {},
): PollingState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [nonce, setNonce] = useState(0)
  const fetcherRef = useRef(fetcher)
  useLayoutEffect(() => {
    fetcherRef.current = fetcher
  })

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  // Turning polling on starts a load; while it is off nothing loads (derived below).
  const [wasEnabled, setWasEnabled] = useState(enabled)
  if (wasEnabled !== enabled) {
    setWasEnabled(enabled)
    if (enabled) setLoading(true)
  }

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let failures = 0

    const tick = async () => {
      if (document.hidden) {
        timer = setTimeout(tick, intervalMs)
        return
      }
      try {
        const result = await fetcherRef.current()
        if (cancelled) return
        failures = 0
        setData(result)
        setError(null)
        setUpdatedAt(Date.now())
      } catch (err) {
        if (cancelled) return
        failures += 1
        setError(err)
      } finally {
        if (!cancelled) {
          setLoading(false)
          timer = setTimeout(tick, Math.min(intervalMs * 2 ** failures, maxIntervalMs))
        }
      }
    }
    void tick()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [enabled, intervalMs, maxIntervalMs, nonce])

  return { data, error, updatedAt, loading: enabled && loading, refresh }
}
