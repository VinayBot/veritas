import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Ban, Brain, ChevronDown, Clock, Eraser, RotateCcw, Send, Square, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Stepper, type StepperStep, type StepState } from '@/components/ui/stepper'
import { AlertBanner } from '@/components/ui/alert-banner'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { useCommands, type CommandPaletteItem } from '@/components/ui/command-palette'
import { AnalystBot, type BotState } from '@/components/robot/analyst-bot'
import { AnalysisPanel } from '@/components/workspace/AnalysisPanel'
import { AnswerText } from '@/components/workspace/AnswerText'
import { ModelPicker } from '@/components/workspace/ModelPicker'
import { RecommendationCard } from '@/components/workspace/RecommendationCard'
import { StrategyPicker } from '@/components/workspace/StrategyPicker'
import { CompareDialog } from '@/components/compare/CompareDialog'
import { SettingsDialog } from '@/components/settings/SettingsDialog'
import { useAppStore, type ChatMessage, type DetailMode } from '@/store/app-store'
import { useTraceEvents } from '@/hooks/useTraceEvents'
import { useDocumentStatus } from '@/hooks/useDocumentStatus'
import { useStrategies } from '@/hooks/useStrategies'
import { cancelDocument, cancelRun, getReport, ingestSample, retryDocument, streamChat, uploadDocument } from '@/lib/api/client'
import { ApiError, type DocumentResponse, type ReportResponse } from '@/lib/api/types'
import { DURATION, EASE_ENTER } from '@/lib/motion'
import { modelName, ms } from '@/lib/format'
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
]

// Everything through "index" makes the document ready for chat; graph and profile are a
// separate background phase, so their fallback state is read off `enrichment_status`.
const CRITICAL_PATH = new Set(['upload', 'parse', 'refine', 'pii_vault', 'chunk', 'embed', 'index'])
const TAKING_LONGER_MS = 20_000
const STAGE_TITLE: Record<string, string> = Object.fromEntries(INGESTION_STAGES.map((s) => [s.id, s.title]))

const STATUS_VARIANT: Record<DocumentResponse['status'], 'success' | 'outline' | 'warning' | 'destructive'> = {
  queued: 'outline',
  running: 'warning',
  ready: 'success',
  failed: 'destructive',
  cancelled: 'outline',
}

/** What the answer pipeline is doing right now, in plain words. */
const STAGE_WORDS: Record<string, string> = {
  guardian_in: 'checking the question',
  semantic_cache: 'found a cached answer',
  planner: 'planning',
  rewriter: 'rewording for search',
  retriever: 'searching the document',
  critic: 'judging the evidence',
  summarizer: 'reading widely',
  synthesizer: 'writing',
  council: 'convening the council',
  verifier: 'verifying claims',
  guardian_out: 'checking the answer',
  retry: 'retrying with a faster model',
}

/** Prefers real per-stage trace events; falls back to the polled document snapshot so the
 * stepper is still meaningful if the socket never connects. */
function stageState(stageId: string, events: ReturnType<typeof useTraceEvents>['events'], doc: DocumentResponse | null): StepState {
  const matching = events.filter((e) => e.stage === stageId)
  if (matching.length > 0) {
    const latest = matching[matching.length - 1]
    if (latest.status === 'done') return 'complete'
    if (latest.status === 'error' || latest.status === 'blocked') return 'error'
    return 'active'
  }
  if (!doc) return 'pending'
  if (CRITICAL_PATH.has(stageId)) {
    const order = INGESTION_STAGES.map((s) => s.id)
    const stageIndex = order.indexOf(stageId)
    const currentIndex = doc.current_stage ? order.indexOf(doc.current_stage) : -1
    if (doc.status === 'ready' || (doc.status === 'failed' && stageIndex < currentIndex)) return 'complete'
    if (doc.status === 'failed' && doc.error_stage === stageId) return 'error'
    if (doc.current_stage === stageId) return 'active'
    if (currentIndex >= 0 && stageIndex < currentIndex) return 'complete'
    return 'pending'
  }
  return doc.enrichment_status === 'done' ? 'complete' : 'pending'
}

let messageCounter = 0
const newId = () => `m${Date.now()}-${messageCounter++}`
const NO_MESSAGES: ChatMessage[] = []
const STARTERS = ['What is this document about?', 'What are the key rules or requirements?', 'Explain the most important points in detail']

export function WorkspacePage() {
  const store = useAppStore()
  const { documentId, documentName, sessionId, lastReportId, focusedReportId, detailMode, strategyOverride } = store
  const reduced = useReducedMotion()
  const messages = useAppStore((s) => (documentId ? (s.conversations[documentId] ?? NO_MESSAGES) : NO_MESSAGES))

  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const { doc, refresh: refreshDoc } = useDocumentStatus(documentId)
  const { events } = useTraceEvents(documentId)
  const strategies = useStrategies(doc?.status === 'ready' ? documentId : null, doc?.enrichment_status)
  const [input, setInput] = useState('')
  const [revealPii, setRevealPii] = useState(false)
  const [sending, setSending] = useState(false)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [showSteps, setShowSteps] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const [stageStartedAt, setStageStartedAt] = useState(() => Date.now())
  const [sendStartedAt, setSendStartedAt] = useState<number | null>(null)
  const [hoveredChunk, setHoveredChunk] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [compare, setCompare] = useState<{ query?: string; selected?: string[]; comparisonId?: string } | null>(null)
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [reportError, setReportError] = useState<unknown>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const prevStatusRef = useRef<DocumentResponse['status'] | null>(null)
  const atBottomRef = useRef(true)
  const [atBottom, setAtBottom] = useState(true)

  const steps: StepperStep[] = useMemo(
    () => INGESTION_STAGES.map((s) => ({ id: s.id, title: s.title, state: stageState(s.id, events, doc) })),
    [events, doc],
  )

  const strategyNames = useMemo(
    () => Object.fromEntries((strategies.data?.strategies ?? []).map((s) => [s.id, s.display_name])),
    [strategies.data],
  )
  const nameOf = useCallback((id: string | null | undefined) => (id ? (strategyNames[id] ?? id.replace(/_/g, ' ')) : ''), [strategyNames])
  const defaultStrategy = strategies.data?.default ?? null
  const activeStrategy = strategyOverride ?? defaultStrategy

  // A chosen strategy that stopped being available (index deleted, model stopped) is dropped.
  useEffect(() => {
    if (!strategyOverride || !strategies.data) return
    const chosen = strategies.data.strategies.find((s) => s.id === strategyOverride)
    if (!chosen?.available) store.setStrategyOverride(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reacts to availability only
  }, [strategies.data, strategyOverride])

  // Follow new text only while the reader is already at the bottom.
  useEffect(() => {
    if (!atBottomRef.current) return
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: reduced ? 'auto' : 'smooth' })
  }, [messages, reduced])

  function handleChatScroll() {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48
    atBottomRef.current = nearBottom
    setAtBottom(nearBottom)
  }

  function jumpToLatest() {
    const el = scrollRef.current
    if (!el) return
    atBottomRef.current = true
    setAtBottom(true)
    el.scrollTo({ top: el.scrollHeight, behavior: reduced ? 'auto' : 'smooth' })
  }

  const inFlight = doc?.status === 'queued' || doc?.status === 'running'
  // One clock for the two things that show elapsed time: an ingest stage and a pending answer.
  useEffect(() => {
    if (!inFlight && !sending) return
    const interval = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(interval)
  }, [inFlight, sending])

  useEffect(() => {
    if (!doc) return
    if (doc.current_stage !== null) setStageStartedAt(Date.now())
    if (prevStatusRef.current !== null && prevStatusRef.current !== 'ready' && doc.status === 'ready') {
      toast.success(`"${documentName ?? doc.filename}" is ready — ${doc.chunk_count ?? 0} chunks indexed`)
    }
    prevStatusRef.current = doc.status
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the fields that matter
  }, [doc?.status, doc?.current_stage])

  const stageElapsedMs = now - stageStartedAt
  const takingLonger = inFlight && stageElapsedMs > TAKING_LONGER_MS

  // The analysis panel shows the answer the reader picked, or the latest one.
  const shownReportId = focusedReportId ?? lastReportId
  useEffect(() => {
    if (!shownReportId) {
      setReport(null)
      return
    }
    let cancelled = false
    setReportError(null)
    getReport(shownReportId)
      .then((data) => !cancelled && setReport(data))
      .catch((err) => !cancelled && setReportError(err))
    return () => {
      cancelled = true
    }
  }, [shownReportId])

  async function startIngest(run: () => Promise<{ document_id: string }>, name: string) {
    setUploading(true)
    setStageStartedAt(Date.now())
    prevStatusRef.current = 'queued'
    try {
      const { document_id } = await run()
      store.setDocument(document_id, name)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const handleFile = (file: File) => startIngest(() => uploadDocument(file), file.name)
  const handleSample = () => startIngest(ingestSample, 'northwind_remote_work_travel_policy.pdf')

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

  async function handleCancelIngest() {
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

  async function handleSend(text = input.trim(), overrideDetail?: DetailMode) {
    if (!text || sending || doc?.status !== 'ready' || !documentId) return
    const docId = documentId
    const assistantId = newId()
    const detail = overrideDetail ?? detailMode
    setInput('')
    store.setFocusedReportId(null)
    store.appendMessages(docId, [
      { id: newId(), role: 'user', content: text },
      { id: assistantId, role: 'assistant', content: '', streaming: true, pendingStrategy: activeStrategy ?? undefined },
    ])
    setSending(true)
    setSendStartedAt(Date.now())
    atBottomRef.current = true
    const patch = (update: (m: ChatMessage) => ChatMessage) => store.updateMessage(docId, assistantId, update)

    try {
      await streamChat(
        {
          message: text,
          document_id: docId,
          strategy: strategyOverride,
          detail,
          reveal_pii: revealPii,
          session_id: sessionId,
        },
        (evt) => {
          switch (evt.event) {
            case 'session':
              store.setSession(evt.data.session_id)
              setActiveRunId(evt.data.run_id)
              patch((m) => ({ ...m, pendingStrategy: evt.data.strategy, pendingDetail: evt.data.detail }))
              break
            case 'stage':
              patch((m) => ({ ...m, stage: evt.data.stage }))
              break
            case 'token':
              patch((m) => ({ ...m, content: m.content + evt.data }))
              break
            case 'replace':
              patch((m) => ({ ...m, content: evt.data }))
              break
            case 'citations':
              patch((m) => ({ ...m, citations: evt.data }))
              break
            case 'agent_steps':
              patch((m) => ({ ...m, agentSteps: evt.data }))
              break
            case 'routing':
              patch((m) => ({ ...m, routing: evt.data }))
              break
            case 'council_run_id':
              patch((m) => ({ ...m, councilRunId: evt.data }))
              break
            case 'answer':
              // The answer is complete: unlock the composer now, while scoring continues.
              patch((m) => ({ ...m, summary: evt.data, streaming: false, scoring: true, stage: undefined }))
              setSending(false)
              break
            case 'quality':
              patch((m) => ({ ...m, quality: evt.data ?? undefined, scoring: false }))
              break
            case 'done':
              patch((m) => ({ ...m, reportId: evt.data.report_id, scoring: false }))
              store.setLastReportId(evt.data.report_id)
              break
            case 'error':
              // If the answer was already delivered, keep it and note what failed after.
              patch((m) =>
                m.summary
                  ? { ...m, scoring: false, errorCode: evt.data.code }
                  : { ...m, content: evt.data.message, errored: true, errorCode: evt.data.code, streaming: false, scoring: false },
              )
              break
          }
        },
      )
    } catch (err) {
      patch((m) => (m.summary ? m : { ...m, content: 'The request failed before an answer arrived. Is the backend running?', errored: true, streaming: false }))
      toast.error(err instanceof Error ? err.message : 'Chat request failed')
    } finally {
      patch((m) => ({ ...m, streaming: false, scoring: false }))
      setSending(false)
      setActiveRunId(null)
      setSendStartedAt(null)
      strategies.refresh() // a new answer may have given a strategy a measured latency
    }
  }

  const commands = useMemo<CommandPaletteItem[]>(() => {
    const items: CommandPaletteItem[] = [
      { id: 'toggle-deep', label: 'Toggle Deep reasoning (7–8 line answers)', group: 'Answers', onSelect: () => store.setDetailMode(useAppStore.getState().detailMode === 'deep' ? 'brief' : 'deep') },
      { id: 'open-models', label: 'Switch model…', group: 'Models', keywords: 'llm ollama generator judge embedding', onSelect: () => setSettingsOpen(true) },
    ]
    for (const s of strategies.data?.strategies ?? []) {
      if (!s.available) continue
      items.push({
        id: `strategy-${s.id}`,
        label: `Switch strategy: ${s.display_name}`,
        group: 'Strategy',
        keywords: `rag ${s.best_for}`,
        onSelect: () => store.setStrategyOverride(s.is_default ? null : s.id),
      })
    }
    return items
    // eslint-disable-next-line react-hooks/exhaustive-deps -- store setters are stable
  }, [strategies.data])
  useCommands('workspace', commands)

  const enriching = doc?.enrichment_status === 'running'
  const botState: BotState = doc?.status === 'failed' ? 'error' : inFlight || uploading || sending || enriching ? 'working' : report ? 'success' : 'idle'
  const botLabel =
    doc?.status === 'failed'
      ? 'Ingestion failed'
      : inFlight
        ? `${STAGE_TITLE[doc?.current_stage ?? ''] ?? 'Starting'}…`
        : sending
          ? 'Answering…'
          : enriching
            ? 'Building the knowledge graph and profiling the document…'
            : report
              ? 'Answer analysed'
              : doc?.status === 'ready'
                ? 'Ready — ask anything about this document'
                : 'Waiting for a document'

  // ---- no document yet -------------------------------------------------------------------
  if (!documentId) {
    return (
      <div className="relative flex min-h-0 flex-1 flex-col items-center justify-center gap-8 overflow-hidden p-6" data-testid="workspace-empty">
        <div className="ember-field" aria-hidden="true">
          {Array.from({ length: 14 }).map((_, i) => (
            <span
              key={i}
              style={{
                left: `${6 + i * 6.7}%`,
                animationDuration: `${7 + (i % 5) * 1.6}s`,
                animationDelay: `${(i % 7) * 0.9}s`,
                ['--drift' as string]: `${(i % 2 ? 1 : -1) * (1 + (i % 4))}rem`,
              }}
            />
          ))}
        </div>
        <AnalystBot state={uploading ? 'working' : 'idle'} size={150} />
        <div className="max-w-xl text-center">
          <h1 className="font-display text-3xl font-semibold tracking-tight text-foreground">Ask your documents. See exactly how the answer was found.</h1>
          <p className="mt-3 text-sm text-muted-foreground">
            Upload a document and Veritas ingests it, recommends how to search it, and answers with citations you can check.
          </p>
        </div>
        <div
          role="button"
          tabIndex={0}
          aria-label="Upload a document"
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              fileInputRef.current?.click()
            }
          }}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const file = e.dataTransfer.files[0]
            if (file) void handleFile(file)
          }}
          data-dragging={dragging}
          className="dropzone lacquer-card flex w-full max-w-xl cursor-pointer flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-border bg-surface/80 px-6 py-10 text-center outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <Upload className="size-7 text-accent" aria-hidden="true" />
          <p className="font-medium text-foreground">{uploading ? 'Uploading…' : 'Drop a document here, or click to browse'}</p>
          <p className="text-xs text-muted-foreground">PDF, DOCX, PPTX, XLSX, HTML, Markdown, TXT, CSV, EML, RTF, DOC, XLS · up to 25 MB</p>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void handleFile(file)
            }}
          />
        </div>
        <Button variant="outline" size="sm" disabled={uploading} data-testid="load-sample-document" onClick={() => void handleSample()}>
          Or try the bundled sample (a remote-work and travel policy PDF)
        </Button>
      </div>
    )
  }

  // ---- with a document -------------------------------------------------------------------
  return (
    <div className="flex min-h-0 flex-1 gap-5 p-5">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <h1 className="blade-edge truncate font-display text-xl font-semibold tracking-tight text-foreground">{documentName ?? 'Workspace'}</h1>
            {doc && (
              <Badge variant={STATUS_VARIANT[doc.status]} data-testid="document-status">
                {doc.status}
              </Badge>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StrategyPicker
              documentId={documentId}
              data={strategies.data}
              error={strategies.error}
              selected={strategyOverride}
              onSelect={store.setStrategyOverride}
              onChanged={(next) => {
                if (next) strategies.setData({ ...next, document_id: documentId })
                strategies.refresh()
              }}
            />
            <ModelPicker onOpenSettings={() => setSettingsOpen(true)} />
            {inFlight && (
              <Button variant="ghost" size="sm" disabled={cancelling} onClick={() => void handleCancelIngest()}>
                <Ban className="size-3.5" /> Cancel
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={() => store.setDocument(null, null)} data-testid="new-document">
              New document
            </Button>
          </div>
        </header>

        {/* Ingestion: the full stepper while it runs, one line once it is done. */}
        <section className="rounded-xl border border-border bg-surface px-4 py-3" aria-label="Ingestion status" data-testid="ingestion-card">
          {doc?.status === 'ready' && !showSteps ? (
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <p data-testid="ingestion-summary">
                <span className="text-foreground">{doc.chunk_count ?? 0} chunks</span> ({doc.chunk_strategy ?? '—'}) · {doc.graph_entity_count ?? 0} entities ·{' '}
                {doc.graph_triple_count ?? 0} relations
                {Object.keys(doc.pii_counts).length > 0 && (
                  <>
                    {' '}
                    · PII masked:{' '}
                    {Object.entries(doc.pii_counts)
                      .map(([k, v]) => `${k} ×${v}`)
                      .join(', ')}
                  </>
                )}
                {enriching && <span className="text-live"> · building the graph and profile in the background…</span>}
                {doc.enrichment_status === 'failed' && <span className="text-warning"> · background enrichment failed (chat is unaffected)</span>}
              </p>
              <button type="button" className="underline-offset-2 hover:underline" onClick={() => setShowSteps(true)}>
                Show pipeline
              </button>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <Stepper steps={steps} status={doc ? 'success' : 'loading'} />
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                {inFlight && doc ? (
                  <p className="flex items-center gap-1.5">
                    <Clock className="size-3.5" /> {STAGE_TITLE[doc.current_stage ?? ''] ?? doc.current_stage ?? 'starting'} · {Math.round(stageElapsedMs / 1000)}s
                    elapsed
                  </p>
                ) : (
                  <span />
                )}
                {doc?.status === 'ready' && (
                  <button type="button" className="underline-offset-2 hover:underline" onClick={() => setShowSteps(false)}>
                    Hide pipeline
                  </button>
                )}
              </div>
            </>
          )}
          <AnimatePresence>
            {takingLonger && doc && (
              <AlertBanner
                variant="warning"
                title={`Taking longer than expected — still on "${STAGE_TITLE[doc.current_stage ?? ''] ?? doc.current_stage}"`}
                description="A first run can be slow while a model downloads or loads into memory. The pipeline is still working; see docs/TROUBLESHOOTING.md if it does not move."
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
        </section>

        <div className="relative min-h-0 flex-1">
          <div
            ref={scrollRef}
            onScroll={handleChatScroll}
            className="h-full overflow-y-auto rounded-xl border border-border bg-surface p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            data-testid="chat-scroll-pane"
            tabIndex={0}
            role="log"
            aria-label="Chat messages"
          >
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
                <p className="text-sm text-muted-foreground">
                  {doc?.status === 'ready' ? 'Ask something about this document.' : 'You can ask questions as soon as ingestion finishes.'}
                </p>
                {doc?.status === 'ready' && (
                  <div className="stagger flex max-w-lg flex-wrap justify-center gap-2">
                    {STARTERS.map((q) => (
                      <button
                        key={q}
                        type="button"
                        onClick={() => void handleSend(q)}
                        className="rise-in rounded-pill border border-border bg-surface-raised px-3 py-1.5 text-xs text-foreground transition-colors duration-micro hover:border-accent/60"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {messages.map((m) => (
                  <MessageBubble
                    key={m.id}
                    message={m}
                    nameOf={nameOf}
                    elapsedMs={m.streaming && sendStartedAt ? now - sendStartedAt : null}
                    selected={m.reportId !== undefined && m.reportId === shownReportId}
                    hoveredChunk={hoveredChunk}
                    onHoverChunk={setHoveredChunk}
                    onInspect={() => m.reportId && store.setFocusedReportId(m.reportId)}
                  />
                ))}
              </div>
            )}
          </div>
          {!atBottom && messages.length > 0 && (
            <button
              type="button"
              onClick={jumpToLatest}
              data-testid="jump-to-latest"
              className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-pill border border-border bg-surface-raised px-3 py-1.5 text-xs font-medium text-foreground shadow-md transition-colors duration-micro hover:text-accent"
            >
              <ChevronDown className="size-3.5" /> Jump to latest
            </button>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => store.setDetailMode(detailMode === 'deep' ? 'brief' : 'deep')}
              aria-pressed={detailMode === 'deep'}
              data-testid="deep-reasoning"
              title="Off: a quick answer of 3–4 lines. On: a fuller answer of 7–8 lines, which takes a little longer."
              className={cn(
                'flex items-center gap-1.5 rounded-pill border px-3 py-1 text-xs font-medium transition-colors duration-micro',
                detailMode === 'deep' ? 'border-accent/60 bg-accent/15 text-foreground' : 'border-border text-muted-foreground hover:border-accent/50 hover:text-foreground',
              )}
            >
              <Brain className="size-3.5" aria-hidden="true" /> Deep reasoning
            </button>
            <button
              type="button"
              onClick={() => setRevealPii((v) => !v)}
              aria-pressed={revealPii}
              title="Lets answers include personal data that was masked at ingestion. Each reveal is logged."
              className={cn(
                'rounded-pill border px-3 py-1 text-xs font-medium transition-colors duration-micro',
                revealPii ? 'border-warning/50 bg-warning/10 text-warning' : 'border-border text-muted-foreground hover:text-foreground',
              )}
            >
              Reveal PII
            </button>
            {messages.length > 0 && (
              <button
                type="button"
                onClick={() => store.clearConversation(documentId)}
                className="ml-auto flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <Eraser className="size-3" /> Clear chat
              </button>
            )}
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
              aria-label="Your question"
              placeholder={doc?.status === 'ready' ? 'Ask a question about this document…' : 'Waiting for ingestion to finish before you can chat…'}
              className="min-h-11 flex-1 resize-none"
            />
            {sending && activeRunId ? (
              <Button variant="outline" onClick={() => void cancelRun(activeRunId).catch(() => {})} aria-label="Stop answering" data-testid="stop-answer">
                <Square className="size-4" />
              </Button>
            ) : (
              <Button onClick={() => void handleSend()} disabled={sending || !input.trim() || doc?.status !== 'ready'} aria-label="Send question" data-testid="send-question">
                <Send className="size-4" />
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Right: the analyst — recommendation before the first answer, analysis after. */}
      <aside
        className="hidden min-h-0 w-[420px] shrink-0 flex-col gap-3 overflow-y-auto rounded-xl border border-border bg-surface p-4 lg:flex"
        data-testid="analyst-panel"
        tabIndex={0}
        role="region"
        aria-label="Analyst"
      >
        <AnalystBot state={botState} size={report ? 96 : 150} label={botLabel} />
        {doc?.status === 'ready' && (
          <RecommendationCard
            documentId={documentId}
            enrichmentStatus={doc.enrichment_status}
            nameOf={nameOf}
            onApplied={() => {
              store.setStrategyOverride(null)
              strategies.refresh()
            }}
            // The recommendation rests on the document's question set; comparing on that same set
            // checks it, where a single question can easily disagree.
            onCompare={(selected, comparisonId) => setCompare({ selected, comparisonId })}
          />
        )}
        {reportError ? (
          <ErrorState error={reportError} compact />
        ) : shownReportId && !report ? (
          <LoadingState shape="cards" rows={2} label="Loading the answer analysis" />
        ) : report ? (
          <motion.div
            key={report.id}
            initial={reduced ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: reduced ? 0 : DURATION.standard, ease: EASE_ENTER }}
          >
            <p className="mb-2 truncate text-[11px] text-muted-foreground">
              Analysis of: <span className="text-foreground">{report.query}</span>
            </p>
            <AnalysisPanel
              report={report}
              strategyName={nameOf(report.strategy)}
              hoveredChunk={hoveredChunk}
              onHoverChunk={setHoveredChunk}
              onCompare={() => setCompare({ query: report.query })}
            />
          </motion.div>
        ) : (
          doc?.status === 'ready' && (
            <p className="rounded-xl border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
              Ask a question and this panel will show how the answer was found: what was retrieved and why, how well each sentence is supported, and where
              the time went.
            </p>
          )
        )}
      </aside>

      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      {compare && strategies.data && (
        <CompareDialog
          open
          onOpenChange={(open) => !open && setCompare(null)}
          documentId={documentId}
          strategies={strategies.data.strategies}
          defaultStrategy={strategies.data.default}
          initialQuery={compare.query}
          initialSelected={compare.selected}
          initialComparisonId={compare.comparisonId}
          onAdopted={() => {
            store.setStrategyOverride(null)
            strategies.refresh()
          }}
        />
      )}
    </div>
  )
}

function MessageBubble({
  message,
  nameOf,
  elapsedMs,
  selected,
  hoveredChunk,
  onHoverChunk,
  onInspect,
}: {
  message: ChatMessage
  nameOf: (id: string | null | undefined) => string
  elapsedMs: number | null
  selected: boolean
  hoveredChunk: string | null
  onHoverChunk: (id: string | null) => void
  onInspect: () => void
}) {
  const [showSteps, setShowSteps] = useState(false)
  const reduced = useReducedMotion()
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="pop-in max-w-[85%] rounded-2xl rounded-br-md border border-accent/25 bg-accent/12 px-3.5 py-2.5 text-sm whitespace-pre-wrap text-foreground">{message.content}</div>
      </div>
    )
  }
  const summary = message.summary
  const grounding = message.quality?.grounding
  const waiting = message.streaming && message.content === ''
  return (
    <motion.div
      initial={reduced ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduced ? 0 : DURATION.standard, ease: EASE_ENTER }}
      className="flex flex-col items-start gap-1.5"
      data-testid="assistant-message"
      data-outcome={summary?.outcome}
    >
      <div
        className={cn(
          'max-w-[88%] rounded-2xl rounded-bl-md border px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap text-foreground',
          message.errored ? 'border-danger/40 bg-danger/10' : selected ? 'border-foreground/25 bg-surface-raised' : 'border-border bg-surface-raised',
        )}
      >
        {waiting ? (
          <span className="flex items-center gap-2 text-muted-foreground" role="status" data-testid="answer-pending">
            <span className="flex gap-1" aria-hidden="true">
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className="size-1.5 rounded-full bg-live"
                  animate={reduced ? undefined : { opacity: [0.3, 1, 0.3], y: [0, -2, 0] }}
                  transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }}
                />
              ))}
            </span>
            {STAGE_WORDS[message.stage ?? ''] ?? 'starting'}
            {message.pendingStrategy && <span>· {nameOf(message.pendingStrategy)}</span>}
            {elapsedMs !== null && <span className="tabular-nums">· {(elapsedMs / 1000).toFixed(0)}s</span>}
          </span>
        ) : message.errored ? (
          <span role="alert">{message.content}</span>
        ) : (
          <span className={message.streaming ? 'typing-caret' : undefined}>
          <AnswerText content={message.content} citations={message.citations ?? []} grounding={grounding} hoveredChunk={hoveredChunk} onHoverChunk={onHoverChunk} />
          </span>
        )}
      </div>

      {summary && (
        <div className="flex max-w-[88%] flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground" data-testid="answer-meta">
          <span>
            Answered with: <span className="font-medium text-foreground">{nameOf(summary.strategy)}</span>
          </span>
          <span>· {summary.detail === 'deep' ? 'deep' : 'quick'}</span>
          <span className="tabular-nums" data-testid="answer-latency">
            · {ms(summary.latency_ms)}
          </span>
          {message.routing && (
            <span>
              · {modelName(message.routing.model_used)}
              {message.routing.fell_back ? ' (fallback)' : ''}
            </span>
          )}
          {summary.cache_hit && <Badge variant="outline">cached</Badge>}
          {message.councilRunId && <Badge variant="glow">council</Badge>}
          {message.scoring ? (
            <span className="flex items-center gap-1" role="status">
              <Skeleton className="h-3 w-16" /> scoring…
            </span>
          ) : message.quality ? (
            <Badge variant="outline" data-testid="answer-quality-badge" title="Scored by a judge model without a reference answer.">
              estimated ·{' '}
              {grounding
                ? `${grounding.supported}/${grounding.total} sentences supported`
                : message.quality.confidence !== null
                  ? `confidence ${Math.round(message.quality.confidence * 100)}%`
                  : 'not measured'}
            </Badge>
          ) : null}
          {message.errorCode === 'report_failed' && <Badge variant="warning">analysis could not be saved</Badge>}
          {message.reportId && (
            <button type="button" onClick={onInspect} className={cn('underline-offset-2 hover:underline', selected && 'text-accent-soft')} data-testid="inspect-answer">
              {selected ? 'shown in the analysis panel' : 'view analysis'}
            </button>
          )}
          {!!message.agentSteps?.length && (
            <button type="button" onClick={() => setShowSteps((v) => !v)} aria-expanded={showSteps} className="underline-offset-2 hover:underline">
              {message.agentSteps.length} step{message.agentSteps.length === 1 ? '' : 's'}
            </button>
          )}
        </div>
      )}
      {showSteps && message.agentSteps && (
        <ol className="flex max-w-[88%] flex-col gap-1 border-l border-border pl-3 text-xs text-muted-foreground">
          {message.agentSteps.map((s, i) => (
            <li key={i}>
              <span className="font-medium text-foreground">{s.node.replace(/_/g, ' ')}</span>: {s.summary}
            </li>
          ))}
        </ol>
      )}
    </motion.div>
  )
}
