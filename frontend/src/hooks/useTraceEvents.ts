import { authQuery } from '@/lib/api/client'
import { useEffect, useRef, useState } from 'react'
import type { TraceEvent } from '@/lib/api/types'

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 10_000

export type SocketState = 'idle' | 'connecting' | 'open' | 'closed'

/**
 * Subscribes to /ws/trace/{sessionId}. Every event is real, published by the backend's
 * trace bus as a pipeline stage runs; this hook never synthesizes one.
 *
 * `socket` is the connection's actual state: "idle" with no session to watch, "open" only
 * while the socket is connected. Anything that animates from trace events must stop when it
 * is not "open". A dropped socket reconnects with exponential backoff; the server replays
 * history on reconnect, de-duplicated here by `seq`.
 *
 * `enabled: false` closes the socket (used by the Architecture tab's disconnect control).
 */
export function useTraceEvents(
  sessionId: string | null,
  { enabled = true }: { enabled?: boolean } = {},
): {
  events: TraceEvent[]
  connected: boolean
  socket: SocketState
} {
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [socket, setSocket] = useState<SocketState>('idle')
  const sessionIdRef = useRef(sessionId)

  useEffect(() => {
    setEvents([])
  }, [sessionId])

  useEffect(() => {
    sessionIdRef.current = sessionId
    if (!sessionId) {
      setSocket('idle')
      return
    }
    if (!enabled) {
      setSocket('closed')
      return
    }

    let intentionallyClosed = false
    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0

    const connect = () => {
      setSocket('connecting')
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      ws = new WebSocket(`${protocol}//${window.location.host}/ws/trace/${sessionId}${authQuery()}`)

      ws.onopen = () => {
        attempt = 0
        setSocket('open')
      }
      ws.onclose = () => {
        if (intentionallyClosed) return
        setSocket('closed')
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS)
        attempt += 1
        reconnectTimer = setTimeout(connect, delay)
      }
      ws.onerror = () => setSocket('closed')
      ws.onmessage = (ev: MessageEvent<string>) => {
        try {
          const parsed = JSON.parse(ev.data) as TraceEvent
          if (sessionIdRef.current !== sessionId) return
          setEvents((prev) => {
            // A reconnect replays the full history; de-dupe on (seq, status) — a stage's
            // running and done events share nothing but the session, and seq is unique.
            if (prev.some((e) => e.seq === parsed.seq)) return prev
            return [...prev, parsed].sort((a, b) => a.seq - b.seq)
          })
        } catch {
          // Malformed frame: drop it rather than crash the feed.
        }
      }
    }
    connect()

    return () => {
      intentionallyClosed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [sessionId, enabled])

  return { events, connected: socket === 'open', socket }
}
