/**
 * A single shared requestAnimationFrame loop for any continuously-running
 * visual effect (ambient glow, cursor-trail easing, ...), rather than letting
 * every component that wants per-frame updates start its own rAF loop.
 *
 * The loop is started lazily on the first subscriber and cancelled when the
 * last one unsubscribes. It is also explicitly cancelled on
 * `document.visibilitychange` when the tab is hidden, and restarted if there
 * are still subscribers when it becomes visible again — belt-and-suspenders
 * on top of the browser's own rAF throttling in background tabs, so the
 * pause is explicit and reviewable rather than merely assumed.
 */

type Tick = (deltaMs: number) => void

const subscribers = new Set<Tick>()
let rafHandle: number | null = null
let lastTime = 0

function frame(time: number) {
  const delta = lastTime ? time - lastTime : 0
  lastTime = time
  for (const tick of subscribers) tick(delta)
  rafHandle = requestAnimationFrame(frame)
}

function start() {
  if (rafHandle !== null) return
  if (typeof document !== 'undefined' && document.hidden) return
  lastTime = 0
  rafHandle = requestAnimationFrame(frame)
}

function stop() {
  if (rafHandle === null) return
  cancelAnimationFrame(rafHandle)
  rafHandle = null
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stop()
    } else if (subscribers.size > 0) {
      start()
    }
  })
}

/** Subscribe a callback to the shared frame loop. Returns an unsubscribe function. */
export function subscribeToFrameLoop(tick: Tick): () => void {
  subscribers.add(tick)
  start()
  return () => {
    subscribers.delete(tick)
    if (subscribers.size === 0) stop()
  }
}
