import { useCallback, useEffect, useRef, useState } from 'react'
import { getDocument } from '@/lib/api/client'
import type { DocumentResponse } from '@/lib/api/types'

const POLL_INTERVAL_MS = 2000
const TERMINAL_STATUSES = new Set(['ready', 'failed', 'cancelled'])

/** The authoritative source of a document's ingestion status — this is what fixes the
 * "hangs on Ingesting..." bug (docs/TROUBLESHOOTING.md): ingestion is a detached background
 * job now, so a single snapshot right after upload is stale almost immediately. This polls
 * GET /documents/{id} every 2s until the job reaches a terminal status, exactly the "fall
 * back to polling" behavior the trace WebSocket needs when it's slow, blocked, or just
 * doesn't carry the overall job status/error (it only carries per-stage trace events). */
export function useDocumentStatus(documentId: string | null): {
  doc: DocumentResponse | null
  refresh: () => void
} {
  const [doc, setDoc] = useState<DocumentResponse | null>(null)
  const documentIdRef = useRef(documentId)
  const [refreshNonce, setRefreshNonce] = useState(0)

  const refresh = useCallback(() => setRefreshNonce((n) => n + 1), [])

  useEffect(() => {
    documentIdRef.current = documentId
    setDoc(null)
    if (!documentId) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const poll = () => {
      getDocument(documentId)
        .then((detail) => {
          if (cancelled || documentIdRef.current !== documentId) return
          setDoc(detail)
          if (!TERMINAL_STATUSES.has(detail.status)) {
            timer = setTimeout(poll, POLL_INTERVAL_MS)
          }
        })
        .catch(() => {
          if (cancelled || documentIdRef.current !== documentId) return
          // A transient network hiccup shouldn't stop polling forever — retry on the same
          // cadence rather than leaving the UI stuck on the last-known state.
          timer = setTimeout(poll, POLL_INTERVAL_MS)
        })
    }
    poll()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refreshNonce is a manual re-poll trigger, not a value read inside
  }, [documentId, refreshNonce])

  return { doc, refresh }
}
