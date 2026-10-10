import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { AnimatePresence } from 'framer-motion'
import {
  Upload,
  Send,
  Loader2,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  Ban,
  Clock,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Stepper, type StepperStep, type StepState } from '@/components/ui/stepper'
import { AlertBanner } from '@/components/ui/alert-banner'
import { useAppStore } from '@/store/app-store'
import { useTraceEvents } from '@/hooks/useTraceEvents'
import { useDocumentStatus } from '@/hooks/useDocumentStatus'
import { uploadDocument, retryDocument, cancelDocument, streamChat, ApiError } from '@/lib/api/client'
import type {
  ChatCitation,
  AgentStep,
  QualityReport,
  RoutingInfo,
  ChatMode,
  DocumentResponse,
} from '@/lib/api/types'
import { cn } from '@/lib/utils'

const INGESTION_STAGES: { id: string; title: string }[] = [
  { id: 'upload', title: 'Upload' },
  { id: 'parse', title: 'Parse' },
  { id: 'refine', title: 'Refine' },
  { id: 'pii_vault', title: 'PII vault' },
  { id: 'chunk', title: 'Chunk' },
  { id: 'embed', title: 'Embed' },
  { id: 'index', title: 'Index' },
  { id: 'graph', title: 'Graph' },
  { id: 'profile', title: 'Profile' },
  { id: 'advisor', title: 'Advisor' },
]

// Everything through "index" marks the document ready for chat (app/ingestion/service.py's
// critical path); graph/profile/advisor are the separate, non-blocking enrichment phase that
// runs afterward — so their fallback state (when no trace event has arrived yet) has to be
// read off `enrichment_status`, not `current_stage`/`status`, which graph/profile/advisor
// never touch.
const CRITICAL_PATH_STAGE_IDS = new Set(['upload', 'parse', 'refine', 'pii_vault', 'chunk', 'embed', 'index'])
const TAKING_LONGER_MS = 20_000

const STAGE_TITLE: Record<string, string> = Object.fromEntries(
  INGESTION_STAGES.map((s) => [s.id, s.title]),
)

const STATUS_BADGE_VARIANT: Record<DocumentResponse['status'], 'success' | 'outline' | 'warning' | 'destructive'> = {
  queued: 'outline',
  running: 'warning',
  ready: 'success',
  failed: 'destructive',
  cancelled: 'outline',
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: ChatCitation[]
  agentSteps?: AgentStep[]
  quality?: QualityReport
  routing?: RoutingInfo | null
  councilRunId?: string | null
  reportId?: string
  errored?: boolean
}

/** Prefers real per-stage trace events (richer, exact timing) when the WebSocket has
 * delivered any; otherwise falls back to the authoritative polled `doc` snapshot — so the
 * Stepper is still meaningful (never stuck showing "pending" forever) even if the socket
 * never connects at all, per docs/TROUBLESHOOTING.md's "fall back to polling" requirement. */
function stageState(
  stageId: string,
  events: ReturnType<typeof useTraceEvents>['events'],
  doc: DocumentResponse | null,
): StepState {
  const matching = events.filter((e) => e.stage === stageId)
  if (matching.length > 0) {
    const latest = matching[matching.length - 1]
    if (latest.status === 'done') return 'complete'
    if (latest.status === 'error' || latest.status === 'blocked') return 'error'
    return 'active'
  }

  if (!doc) return 'pending'

  if (CRITICAL_PATH_STAGE_IDS.has(stageId)) {
    const order = INGESTION_STAGES.map((s) => s.id)
    const stageIndex = order.indexOf(stageId)
    const currentIndex = doc.current_stage ? order.indexOf(doc.current_stage) : -1
    if (doc.status === 'ready' || (doc.status === 'failed' && stageIndex < currentIndex)) {
      return 'complete'
    }
    if (doc.status === 'failed' && doc.error_stage === stageId) return 'error'
    if (doc.current_stage === stageId) return 'active'
    if (currentIndex >= 0 && stageIndex < currentIndex) return 'complete'
    return 'pending'
  }

  // Enrichment stages (graph/profile/advisor): coarse-grained on purpose — enrichment_status
  // doesn't say *which* of the three is running, and a failed/cancelled enrichment must never
  // read as "ingestion failed" here (the document is still ready and chattable regardless;
  // see the separate enrichment note rendered below the Stepper for that detail).
  if (doc.enrichment_status === 'done') return 'complete'
  return 'pending'
}

export function WorkspacePage() {
  const { documentId, documentName, sessionId, setDocument, setSession, setLastReportId } =
    useAppStore()
  const [uploading, setUploading] = useState(false)
  const { doc, refresh: refreshDoc } = useDocumentStatus(documentId)
  const { events } = useTraceEvents(documentId)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<ChatMode>('agentic')
  const [council, setCouncil] = useState(false)
  const [revealPii, setRevealPii] = useState(false)
  const [sending, setSending] = useState(false)
  const [expandedSteps, setExpandedSteps] = useState<number | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [showStageDetails, setShowStageDetails] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const [stageStartedAt, setStageStartedAt] = useState(() => Date.now())
  const fileInputRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const prevStatusRef = useRef<DocumentResponse['status'] | null>(null)

  const steps: StepperStep[] = useMemo(
    () =>
      INGESTION_STAGES.map((s) => ({
        id: s.id,
        title: s.title,
        state: stageState(s.id, events, doc),
      })),
    [events, doc],
  )

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  // Ticks once a second only while the job is actually in flight, driving both the elapsed-
  // time readout and the 20s "taking longer than expected" threshold below.
  useEffect(() => {
    if (!doc || doc.status === 'ready' || doc.status === 'failed' || doc.status === 'cancelled') {
      return
    }
    const interval = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [doc?.status])

  // Resets the per-stage clock whenever the real current stage changes, and fires the one
  // "ingestion finished" toast exactly once, on the queued/running -> ready transition — not
  // on every poll tick, and not assumed synchronously from the upload response anymore (that
  // was the root cause of the "stuck on Ingesting..." bug — see docs/TROUBLESHOOTING.md).
  useEffect(() => {
    if (!doc) return
    if (doc.current_stage !== null) setStageStartedAt(Date.now())
    if (prevStatusRef.current !== 'ready' && doc.status === 'ready') {
      toast.success(`"${documentName ?? doc.filename}" is ready — ${doc.chunk_count ?? 0} chunks indexed`)
    }
    prevStatusRef.current = doc.status
  }, [doc, documentName])

  const stageElapsedMs = now - stageStartedAt
  const isInFlight = doc?.status === 'queued' || doc?.status === 'running'
  const takingLonger = isInFlight && stageElapsedMs > TAKING_LONGER_MS

  async function handleFile(file: File) {
    setUploading(true)
    setMessages([])
    setSession(null)
    setStageStartedAt(Date.now())
    prevStatusRef.current = null
    try {
      const { document_id } = await uploadDocument(file)
      setDocument(document_id, file.name)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function handleRetry() {
    if (!documentId) return
    setRetrying(true)
    try {
      await retryDocument(documentId)
      setStageStartedAt(Date.now())
      refreshDoc()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Retry failed')
    } finally {
      setRetrying(false)
    }
  }

  async function handleCancel() {
    if (!documentId) return
    setCancelling(true)
    try {
      await cancelDocument(documentId)
      refreshDoc()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Cancel failed')
    } finally {
      setCancelling(false)
    }
  }

  async function handleSend() {
    const text = input.trim()
    if (!text || sending || doc?.status !== 'ready') return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    setSending(true)

    try {
      await streamChat(
        {
          message: text,
          document_id: documentId,
          mode,
          council,
          reveal_pii: revealPii,
          session_id: sessionId,
        },
        (evt) => {
          // Zustand setters are called here, outside setMessages's updater — calling them
          // from inside a setState updater function is what triggered React's "Cannot update
          // a component while rendering a different component" warning (the updater must stay
          // a pure function of its previous state, with every other side effect kept out of it).
          if (evt.event === 'session') setSession(evt.data.session_id)
          if (evt.event === 'done') setLastReportId(evt.data.report_id)

          // Must be a pure function of `prev` — no mutation of `prev`'s objects. React's
          // <StrictMode> (see main.tsx) deliberately double-invokes a functional setState
          // updater in dev to catch exactly this: the old version did `last.content +=
          // evt.data` on `last`, a reference INTO `prev` (the outer `[...prev]` only copies
          // the array, not its objects) — so the first, supposedly-discarded invocation's
          // mutation was still visible to the second, "real" invocation, which then appended
          // the same delta on top of it. Every real chat answer was silently doubled this
          // way (see docs/TROUBLESHOOTING.md). Fixed by deriving a new message object instead
          // of mutating the old one, so both invocations compute the same, idempotent result.
          setMessages((prev) => {
            const last = prev[prev.length - 1]
            if (!last || last.role !== 'assistant') return prev
            const updated: ChatMessage = { ...last }
            switch (evt.event) {
              case 'token':
                updated.content = last.content + evt.data
                break
              case 'citations':
                updated.citations = evt.data
                break
              case 'agent_steps':
                updated.agentSteps = evt.data
                break
              case 'quality':
                updated.quality = evt.data ?? undefined
                break
              case 'routing':
                updated.routing = evt.data
                break
              case 'council_run_id':
                updated.councilRunId = evt.data
                break
              case 'done':
                updated.reportId = evt.data.report_id
                break
              case 'error':
                updated.content = evt.data.message
                updated.errored = true
                break
            }
            return [...prev.slice(0, -1), updated]
          })
        },
      )
    } catch {
      toast.error('Chat request failed')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="mx-auto flex h-screen max-w-5xl flex-col gap-6 p-6">
      <header>
        <h1 className="font-display text-2xl font-semibold text-foreground">Workspace</h1>
        <p className="text-sm text-muted-foreground">
          Upload a document, then chat with it — every answer, citation and quality score below
          comes from a real backend call, nothing is canned.
        </p>
      </header>

      {!documentId && (
        <Card
          className={cn(
            'flex-1 cursor-pointer items-center justify-center border-2 border-dashed border-border bg-transparent shadow-none transition-colors hover:border-accent/50',
          )}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            const file = e.dataTransfer.files[0]
            if (file) void handleFile(file)
          }}
        >
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            {uploading ? (
              <Loader2 className="size-8 animate-spin text-accent" />
            ) : (
              <Upload className="size-8 text-muted-foreground" />
            )}
            <p className="font-medium text-foreground">
              {uploading ? 'Uploading...' : 'Drop a document here, or click to browse'}
            </p>
            <p className="text-xs text-muted-foreground">
              PDF, DOCX, PPTX, HTML, Markdown, TXT, CSV, EML, RTF
            </p>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) void handleFile(file)
              }}
            />
          </CardContent>
        </Card>
      )}

      {documentId && (
        <>
          <Card size="sm">
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <CardTitle>{documentName ?? documentId}</CardTitle>
                <div className="flex items-center gap-2">
                  {doc && <Badge variant={STATUS_BADGE_VARIANT[doc.status]}>{doc.status}</Badge>}
                  {isInFlight && (
                    <Button variant="ghost" size="sm" disabled={cancelling} onClick={() => void handleCancel()}>
                      <Ban className="size-3.5" /> Cancel
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setDocument(null, null)
                      setMessages([])
                    }}
                  >
                    New document
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <Stepper steps={steps} status={doc ? 'success' : 'loading'} />

              {isInFlight && doc && (
                <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Clock className="size-3.5" />
                  {STAGE_TITLE[doc.current_stage ?? ''] ?? doc.current_stage ?? 'starting'} ·{' '}
                  {Math.round(stageElapsedMs / 1000)}s elapsed
                </p>
              )}

              <AnimatePresence>
                {takingLonger && doc && (
                  <AlertBanner
                    variant="warning"
                    title={`Taking longer than expected — still on "${STAGE_TITLE[doc.current_stage ?? ''] ?? doc.current_stage}"`}
                    description={
                      showStageDetails
                        ? `Elapsed on this stage: ${Math.round(stageElapsedMs / 1000)}s. Trace WebSocket: ${events.length > 0 ? 'connected, receiving events' : 'no events received yet — falling back to polling GET /api/v1/documents/{id} every 2s.'} This can be expected on a first run while a model downloads — see docs/TROUBLESHOOTING.md.`
                        : undefined
                    }
                    actions={
                      <button
                        type="button"
                        onClick={() => setShowStageDetails((v) => !v)}
                        className="text-xs font-medium text-warning underline-offset-2 hover:underline"
                      >
                        {showStageDetails ? 'Hide details' : 'Show details'}
                      </button>
                    }
                    className="mt-3"
                  />
                )}

                {doc?.status === 'failed' && (
                  <AlertBanner
                    variant="danger"
                    title={`Ingestion failed${doc.error_stage ? ` at "${STAGE_TITLE[doc.error_stage] ?? doc.error_stage}"` : ''}`}
                    description={doc.error_message ?? undefined}
                    actions={
                      <Button size="sm" disabled={retrying} onClick={() => void handleRetry()}>
                        <RotateCcw className="size-3.5" /> Retry
                      </Button>
                    }
                    className="mt-3"
                  />
                )}

                {doc?.status === 'cancelled' && (
                  <AlertBanner
                    variant="info"
                    title="Ingestion cancelled"
                    description="You cancelled this job before it finished."
                    actions={
                      <Button size="sm" disabled={retrying} onClick={() => void handleRetry()}>
                        <RotateCcw className="size-3.5" /> Retry
                      </Button>
                    }
                    className="mt-3"
                  />
                )}
              </AnimatePresence>

              {doc?.status === 'ready' && (
                <p className="mt-3 text-xs text-muted-foreground">
                  {doc.chunk_count ?? 0} chunks ({doc.chunk_strategy ?? '—'}) ·{' '}
                  {doc.graph_entity_count ?? 0} entities · {doc.graph_triple_count ?? 0} relations
                  {Object.keys(doc.pii_counts).length > 0 && (
                    <>
                      {' '}
                      · PII masked:{' '}
                      {Object.entries(doc.pii_counts)
                        .map(([k, v]) => `${k} ×${v}`)
                        .join(', ')}
                    </>
                  )}
                  {doc.enrichment_status === 'running' && ' · enriching graph/profile/advisor in the background...'}
                  {doc.enrichment_status === 'failed' &&
                    ' · background graph/profile/advisor enrichment failed (chat is unaffected)'}
                </p>
              )}
            </CardContent>
          </Card>

          <div className="flex min-h-0 flex-1 flex-col gap-3">
            <div ref={scrollRef} className="flex-1 overflow-y-auto rounded-lg border border-border bg-surface p-4">
              {messages.length === 0 && (
                <p className="py-12 text-center text-sm text-muted-foreground">
                  Ask something about this document.
                </p>
              )}
              <div className="flex flex-col gap-4">
                {messages.map((m, i) => (
                  <MessageBubble
                    key={i}
                    message={m}
                    expanded={expandedSteps === i}
                    onToggleExpand={() => setExpandedSteps(expandedSteps === i ? null : i)}
                  />
                ))}
                {sending && messages[messages.length - 1]?.content === '' && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="size-3.5 animate-spin" /> thinking...
                  </div>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {(['agentic', 'hybrid', 'graph'] as ChatMode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={cn(
                    'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                    mode === m
                      ? 'bg-accent text-on-accent'
                      : 'bg-surface-raised text-muted-foreground hover:text-foreground',
                  )}
                >
                  {m}
                </button>
              ))}
              <ToggleChip label="Council" active={council} onToggle={() => setCouncil((v) => !v)} />
              <ToggleChip
                label="Reveal PII"
                active={revealPii}
                onToggle={() => setRevealPii((v) => !v)}
              />
            </div>

            <div className="flex gap-2">
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void handleSend()
                  }
                }}
                disabled={doc?.status !== 'ready'}
                placeholder={
                  doc?.status === 'ready'
                    ? 'Ask a question about this document...'
                    : 'Waiting for ingestion to finish before you can chat...'
                }
                className="min-h-11 flex-1 resize-none"
              />
              <Button
                onClick={() => void handleSend()}
                disabled={sending || !input.trim() || doc?.status !== 'ready'}
              >
                <Send className="size-4" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function ToggleChip({
  label,
  active,
  onToggle,
}: {
  label: string
  active: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
        active
          ? 'border-accent/40 bg-accent/10 text-accent-soft'
          : 'border-border text-muted-foreground hover:text-foreground',
      )}
    >
      {label}
    </button>
  )
}

function MessageBubble({
  message,
  expanded,
  onToggleExpand,
}: {
  message: ChatMessage
  expanded: boolean
  onToggleExpand: () => void
}) {
  const isUser = message.role === 'user'
  return (
    <div className={cn('flex flex-col gap-1.5', isUser ? 'items-end' : 'items-start')}>
      <div
        className={cn(
          'max-w-[85%] rounded-lg px-3.5 py-2.5 text-sm whitespace-pre-wrap',
          isUser
            ? 'bg-accent text-on-accent'
            : message.errored
              ? 'bg-destructive/10 text-destructive'
              : 'bg-surface-raised text-foreground',
        )}
      >
        {message.content || ' '}
      </div>

      {!isUser && (message.citations?.length || message.quality || message.routing) && (
        <div className="flex max-w-[85%] flex-col gap-2">
          {!!message.citations?.length && (
            <div className="flex flex-wrap gap-1.5">
              {message.citations.map((c) => (
                <span
                  key={c.marker}
                  title={c.text}
                  className="cursor-default rounded-full bg-surface-raised px-2 py-0.5 text-xs text-muted-foreground"
                >
                  [{c.marker}] {c.chunk_id.slice(0, 8)}
                </span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            {message.quality && (
              <Badge variant="outline" title={JSON.stringify(message.quality, null, 2)}>
                {message.quality.label}: confidence {Math.round(message.quality.confidence * 100)}%
              </Badge>
            )}
            {message.routing && (
              <Badge variant={message.routing.fell_back ? 'warning' : 'outline'}>
                {message.routing.model_used.replace('ollama/', '')}
                {message.routing.fell_back ? ' (fallback)' : ''} ·{' '}
                {Math.round(message.routing.latency_ms)}ms
              </Badge>
            )}
            {message.councilRunId && (
              <Badge variant="glow">council run {message.councilRunId.slice(0, 8)}</Badge>
            )}
            {!!message.agentSteps?.length && (
              <button
                type="button"
                onClick={onToggleExpand}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {message.agentSteps.length} step{message.agentSteps.length === 1 ? '' : 's'}
                {expanded ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
              </button>
            )}
          </div>
          {expanded && message.agentSteps && (
            <ol className="flex flex-col gap-1 border-l border-border pl-3 text-xs text-muted-foreground">
              {message.agentSteps.map((s, i) => (
                <li key={i}>
                  <span className="font-medium text-foreground">{s.node}</span>: {s.summary}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}
