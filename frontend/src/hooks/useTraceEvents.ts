import { useEffect, useRef, useState } from 'react'
import type { TraceEvent } from '@/lib/api/types'

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 10_000

/** Subscribes to /ws/trace/{sessionId} — every event here is real, published by the backend's
 * trace_bus as pipeline stages actually run (see backend/app/api/routes/trace.py). This hook
 * never synthesizes an event; `events` is empty until the server sends something real.
 *
 * If the socket drops unexpectedly (not because `sessionId` changed or the component
 * unmounted), it reconnects with exponential backoff instead of going silent — see
 * docs/TROUBLESHOOTING.md. This is a nice-to-have for the live per-stage view; the document's
 * overall status/error always comes from useDocumentStatus's polling regardless of whether
 * the socket ever reconnects, so a permanently blocked WebSocket still never hangs the UI. */
export function useTraceEvents(sessionId: string | null): {
  events: TraceEvent[]
  connected: boolean
} {
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [connected, setConnected] = useState(false)
  const sessionIdRef = useRef(sessionId)

  useEffect(() => {
    setEvents([])
    sessionIdRef.current = sessionId
    if (!sessionId) {
      setConnected(false)
      return
    }

    let intentionallyClosed = false
    let socket: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/trace/${sessionId}`)

      socket.onopen = () => {
        attempt = 0
        setConnected(true)
      }
      socket.onclose = () => {
        setConnected(false)
        if (intentionallyClosed) return
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS)
        attempt += 1
        reconnectTimer = setTimeout(connect, delay)
      }
      socket.onerror = () => setConnected(false)
      socket.onmessage = (ev: MessageEvent<string>) => {
        try {
          const parsed = JSON.parse(ev.data) as TraceEvent
          if (sessionIdRef.current !== sessionId) return
          setEvents((prev) => {
            // A reconnect gets the full history replayed from the start (see
            // app/api/routes/trace.py) — without de-duping by `seq`, every event already in
            // `prev` would be appended a second time. Sorting by `seq` too makes `events`
            // safe to treat as the single, deterministic source of truth for replay/scrubbing
            // regardless of the order frames actually arrived in.
            if (prev.some((e) => e.seq === parsed.seq)) return prev
            return [...prev, parsed].sort((a, b) => a.seq - b.seq)
          })
        } catch {
          // Malformed frame — drop it rather than crash the whole trace feed.
        }
      }
    }
    connect()

    return () => {
      intentionallyClosed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [sessionId])

  return { events, connected }
}
