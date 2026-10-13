import { useCallback, useEffect, useState } from 'react'
import { getStrategies } from '@/lib/api/client'
import type { StrategiesResponse } from '@/lib/api/types'

/** The strategy registry with live availability for a document. Re-fetch with `refresh`
 * after anything that could change availability (an index built, the default changed). */
export function useStrategies(documentId: string | null, version: unknown = null) {
  const [data, setData] = useState<StrategiesResponse | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [nonce, setNonce] = useState(0)
  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    getStrategies(documentId)
      .then((result) => {
        if (cancelled) return
        setData(result)
        setError(null)
      })
      .catch((err) => !cancelled && setError(err))
    return () => {
      cancelled = true
    }
  }, [documentId, nonce, version])

  return { data, error, refresh, setData }
}
