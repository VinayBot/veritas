import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { RefreshCw, Search, Sparkles, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/page'
import { StatCard } from '@/components/ui/stat-card'
import { CountUp } from '@/components/ui/count-up'
import { EmptyState, ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { useDocumentStatus } from '@/hooks/useDocumentStatus'
import { useStrategies } from '@/hooks/useStrategies'
import { toast } from 'sonner'
import { ProgressBar } from '@/components/ui/progress-bar'
import { useJob } from '@/hooks/useJob'
import { ApiError, getGraph, getGraphStats, prepareStrategy, streamChat } from '@/lib/api/client'
import type { GraphEdge, GraphNode, GraphStats } from '@/lib/api/types'
import { ms, pct } from '@/lib/format'
import { DURATION, EASE_ENTER } from '@/lib/motion'

// three.js only loads when this section is actually opened.
const KnowledgeGraphCanvas = lazy(() => import('@/components/knowledge-graph/KnowledgeGraphCanvas').then((m) => ({ default: m.KnowledgeGraphCanvas })))

interface GraphAnswer {
  question: string
  text: string
  pending: boolean
  strategy: string | null
  latencyMs: number | null
  citations: number
  entities: string[]
  error: string | null
}

/** The document's entity graph, with a question box: asking runs a real graph traversal
 * (lit up on the graph, entity by entity) and a real answer through the graph strategy. */
export function GraphSection({ documentId }: { documentId: string }) {
  const { doc } = useDocumentStatus(documentId)
  const strategies = useStrategies(documentId, doc?.enrichment_status)
  const reduced = useReducedMotion()
  const [nodes, setNodes] = useState<GraphNode[] | null>(null)
  const [edges, setEdges] = useState<GraphEdge[]>([])
  const [error, setError] = useState<unknown>(null)
  const [stats, setStats] = useState<GraphStats | null>(null)
  const [filter, setFilter] = useState('')
  const [activeFilter, setActiveFilter] = useState<string | undefined>(undefined)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<GraphAnswer | null>(null)
  const [sequence, setSequence] = useState<string[] | undefined>(undefined)
  const [step, setStep] = useState<string | null>(null)
  const askedAt = useRef(0)
  const [buildJobId, setBuildJobId] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const build = useJob(buildJobId, (job) => {
    setBuildJobId(null)
    if (job.status === 'done') {
      toast.success('Knowledge graph rebuilt')
      strategies.refresh()
      setReloadKey((k) => k + 1)
    } else if (job.status === 'failed') toast.error(job.error ?? 'The graph could not be built')
  })

  /** Reads the document's entities and relations again. Takes about a minute. */
  async function rebuild() {
    try {
      setBuildJobId((await prepareStrategy('graph_rag', documentId, true)).job_id)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not start building the graph')
    }
  }

  const fetchGraph = useCallback(
    (query?: string) => {
      getGraph(documentId, query, 2)
        .then((data) => {
          setNodes(data.nodes)
          setEdges(data.edges)
          setError(null)
        })
        .catch(setError)
    },
    [documentId],
  )
  // A filter or a retry clears the graph first, so the spinner shows while it loads.
  const load = useCallback(
    (query?: string) => {
      setNodes(null)
      fetchGraph(query)
    },
    [fetchGraph],
  )

  // Graph extraction is a background phase: re-read when it finishes. A different document or
  // a rebuilt graph also clears the filter and the last answer, while rendering.
  const graphKey = `${documentId}|${doc?.enrichment_status}|${reloadKey}`
  const [graphFor, setGraphFor] = useState(graphKey)
  if (graphFor !== graphKey) {
    setGraphFor(graphKey)
    setActiveFilter(undefined)
    setAnswer(null)
    setSequence(undefined)
    setNodes(null)
  }
  useEffect(() => {
    fetchGraph()
    getGraphStats(documentId)
      .then(setStats)
      .catch(() => setStats(null))
  }, [fetchGraph, documentId, doc?.enrichment_status, reloadKey])

  const selected = useMemo(() => nodes?.find((n) => n.id === selectedId) ?? null, [nodes, selectedId])
  const graphStrategy = strategies.data?.strategies.find((s) => s.id === 'graph_rag')
  const useGraphStrategy = graphStrategy?.available ?? false

  async function ask(e: React.FormEvent) {
    e.preventDefault()
    const text = question.trim()
    if (!text || answer?.pending) return
    askedAt.current = Date.now()
    setStep(null)
    setAnswer({ question: text, text: '', pending: true, strategy: null, latencyMs: null, citations: 0, entities: [], error: null })
    const patch = (update: Partial<GraphAnswer>) => setAnswer((prev) => (prev && prev.question === text ? { ...prev, ...update } : prev))

    // The traversal comes back in well under a second, so the graph lights up while the
    // answer is still being written.
    getGraph(documentId, text, 2)
      .then((data) => {
        const linked = (data.linked_entities ?? []).map((n) => n.id)
        const path = data.nodes.map((n) => n.id).filter((id) => !linked.includes(id))
        setSequence(linked.length + path.length > 0 ? [...linked, ...path] : undefined)
        patch({ entities: (data.linked_entities ?? []).map((n) => n.name) })
      })
      .catch(() => {})

    try {
      await streamChat(
        { message: text, document_id: documentId, strategy: useGraphStrategy ? 'graph_rag' : null, detail: 'brief', reveal_pii: false, session_id: null },
        (evt) => {
          if (evt.event === 'token') setAnswer((prev) => (prev && prev.question === text ? { ...prev, text: prev.text + evt.data } : prev))
          else if (evt.event === 'replace') patch({ text: evt.data })
          else if (evt.event === 'citations') patch({ citations: evt.data.length })
          else if (evt.event === 'answer') patch({ pending: false, strategy: evt.data.strategy, latencyMs: evt.data.latency_ms })
          else if (evt.event === 'error') patch({ pending: false, error: evt.data.message })
        },
      )
    } catch (err) {
      patch({ error: err instanceof Error ? err.message : 'The question could not be sent' })
    } finally {
      patch({ pending: false })
    }
  }

  const topDegree = Math.max(1, ...(stats?.most_connected ?? []).map((n) => n.degree))
  const building = doc?.enrichment_status === 'running'

  return (
    <div className="flex flex-col gap-6" data-testid="eval-graph">
      <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Entities" tip="Distinct people, organisations, places, dates and terms extracted from this document." loading={stats === null && !error} value={stats ? <CountUp value={stats.entities} /> : undefined} className="lacquer-card" testId="graph-kpi-entities" />
        <StatCard label="Relations" tip="Links between two entities, each traceable to the passage it was read from." loading={stats === null && !error} value={stats ? <CountUp value={stats.relations} /> : undefined} className="lacquer-card" />
        <StatCard label="Communities" term="community" loading={stats === null && !error} value={stats ? <CountUp value={stats.communities} /> : undefined} className="lacquer-card" />
        <StatCard
          label="Unconnected entities"
          term="orphan_rate"
          loading={stats === null && !error}
          value={stats && stats.orphan_rate !== null ? pct(stats.orphan_rate, 0) : undefined}
          emptyLabel="No entities yet"
          caption={stats ? `${stats.orphans} of ${stats.entities}` : undefined}
          className="lacquer-card"
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel
          title="Knowledge graph"
          description="Every point of light is an entity read from the document. Drag to rotate, hover for a name, click to inspect."
          actions={
            <>
            <Button size="sm" variant="outline" onClick={() => void rebuild()} disabled={build.active} data-testid="rebuild-graph" title="Read the document's entities and relations again (about a minute).">
              <RefreshCw className={build.active ? 'size-3.5 animate-spin' : 'size-3.5'} /> {build.active ? 'Building…' : 'Rebuild graph'}
            </Button>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                const next = filter.trim() || undefined
                setActiveFilter(next)
                load(next)
              }}
              className="flex items-center gap-1.5"
            >
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by entity…" aria-label="Filter the graph by entity" className="h-8 w-44" />
              <Button type="submit" size="icon-sm" variant="outline" aria-label="Apply filter">
                <Search className="size-3.5" />
              </Button>
              {activeFilter && (
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Clear filter"
                  onClick={() => {
                    setFilter('')
                    setActiveFilter(undefined)
                    load()
                  }}
                >
                  <X className="size-3.5" />
                </Button>
              )}
            </form>
            </>
          }
          testId="graph-panel"
        >
          {build.active && (
            <div className="mb-3 flex flex-col gap-1.5 text-xs text-muted-foreground" data-testid="graph-build-progress">
              <ProgressBar value={build.progress} label="Building the knowledge graph" tone="live" />
              <span className="flex justify-between gap-2">
                <span className="truncate">{build.message ?? 'Starting'}</span>
                <span className="tabular-nums text-foreground">{Math.round(build.progress * 100)}%</span>
              </span>
            </div>
          )}
          <div className="relative h-[520px] overflow-hidden rounded-xl border border-border bg-background">
            {error ? (
              <div className="flex h-full items-center justify-center">
                <ErrorState error={error} action={<Button size="sm" variant="outline" onClick={() => load(activeFilter)}>Retry</Button>} />
              </div>
            ) : nodes === null ? (
              <LoadingState shape="graph" label="Loading the knowledge graph" className="h-full" />
            ) : nodes.length === 0 ? (
              <div className="flex h-full items-center justify-center">
                <EmptyState
                  title={activeFilter ? `Nothing in the graph matches "${activeFilter}"` : building ? 'The graph is still being built' : 'No entities were extracted from this document'}
                  description={
                    activeFilter
                      ? 'Try a different word, or clear the filter.'
                      : building
                        ? 'Entity extraction runs in the background after ingestion. This fills in by itself when it finishes.'
                        : doc?.enrichment_status === 'failed'
                          ? 'Reading the graph did not finish when this document was uploaded. Build it now; it takes about a minute.'
                          : 'Nothing has been read into the graph for this document yet. Build it now; it takes about a minute.'
                  }
                  action={
                    !activeFilter && !building ? (
                      <Button size="sm" onClick={() => void rebuild()} disabled={build.active} data-testid="build-graph">
                        {build.active ? 'Building…' : 'Build the graph'}
                      </Button>
                    ) : undefined
                  }
                />
              </div>
            ) : (
              <Suspense fallback={<LoadingState shape="graph" label="Loading the graph renderer" className="h-full" />}>
                <KnowledgeGraphCanvas nodes={nodes} edges={edges} onSelectEntity={(entity) => setSelectedId(entity?.id ?? null)} highlightSequence={sequence} onHighlightStep={setStep} />
              </Suspense>
            )}

            {nodes !== null && nodes.length > 0 && (
              <form
                onSubmit={(e) => void ask(e)}
                className="absolute top-3 left-1/2 flex w-[min(92%,34rem)] -translate-x-1/2 items-center gap-2 rounded-pill border border-border bg-surface/90 py-1.5 pr-1.5 pl-4 shadow-md backdrop-blur"
                data-testid="ask-the-graph-form"
              >
                <Sparkles className="size-4 shrink-0 text-accent-soft" aria-hidden="true" />
                <input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Ask the graph a question…"
                  aria-label="Ask the graph a question"
                  className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
                  data-testid="ask-the-graph-input"
                />
                <Button type="submit" size="sm" disabled={!question.trim() || answer?.pending} className="rounded-pill">
                  {answer?.pending ? 'Asking…' : 'Ask'}
                </Button>
              </form>
            )}
            {step && nodes && (
              <p className="pointer-events-none absolute top-16 left-1/2 -translate-x-1/2 rounded-pill bg-surface/90 px-3 py-1 text-xs text-live backdrop-blur" aria-live="polite">
                Following: {nodes.find((n) => n.id === step)?.name ?? step}
              </p>
            )}
          </div>

          {answer && (
            <motion.div
              initial={reduced ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: reduced ? 0 : DURATION.standard, ease: EASE_ENTER }}
              className="mt-4 rounded-xl border border-border bg-surface-raised p-4"
              data-testid="graph-answer"
            >
              <p className="text-xs text-muted-foreground">{answer.question}</p>
              {answer.error ? (
                <p className="mt-2 text-sm text-danger" role="alert">
                  {answer.error}
                </p>
              ) : answer.text === '' && answer.pending ? (
                <LoadingState rows={3} label="Writing the answer" className="mt-3" />
              ) : (
                <p className="mt-2 text-sm leading-relaxed whitespace-pre-wrap text-foreground">{answer.text}</p>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                {answer.entities.slice(0, 6).map((name) => (
                  <Badge key={name} variant="glow">
                    {name}
                  </Badge>
                ))}
                {answer.entities.length === 0 && !answer.pending && <span>No entity in the graph matched this question, so the answer came from text search.</span>}
                {answer.strategy && (
                  <span>
                    · answered with {strategies.data?.strategies.find((s) => s.id === answer.strategy)?.display_name ?? answer.strategy} · {ms(answer.latencyMs)} · {answer.citations} citation
                    {answer.citations === 1 ? '' : 's'}
                  </span>
                )}
              </div>
              {!useGraphStrategy && graphStrategy && (
                <p className="mt-2 text-[11px] text-warning">Graph retrieval is unavailable ({graphStrategy.unavailable_reason}); the default strategy answered instead.</p>
              )}
            </motion.div>
          )}
        </Panel>

        <div className="flex min-w-0 flex-col gap-6">
          <Panel title={selected ? selected.name : 'Entity'} description={selected ? undefined : 'Click an entity in the graph to inspect it.'} testId="graph-entity">
            {selected ? (
              <div className="flex flex-col gap-2 text-xs">
                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="outline">{selected.label}</Badge>
                  {selected.community !== null && <Badge variant="glow">community {selected.community}</Badge>}
                </div>
                <p className="text-muted-foreground">
                  {edges.filter((e) => e.source === selected.id || e.target === selected.id).length} relation(s) in view · appears in {selected.doc_ids.length} document
                  {selected.doc_ids.length === 1 ? '' : 's'}
                </p>
                {selected.mentions.length > 0 && <p className="text-muted-foreground">Also written as: {selected.mentions.slice(0, 8).join(', ')}</p>}
                <Button size="sm" variant="outline" className="self-start" onClick={() => setQuestion(`What does the document say about ${selected.name}?`)}>
                  Ask about this
                </Button>
              </div>
            ) : (
              <EmptyState compact title="Nothing selected" />
            )}
          </Panel>

          <Panel title="Most connected" description="Entities with the most relations: what the document is mostly about.">
            {stats === null ? (
              <LoadingState rows={5} label="Loading graph statistics" />
            ) : stats.most_connected.length === 0 ? (
              <EmptyState compact title="No relations yet" />
            ) : (
              <ul className="flex flex-col gap-2">
                {stats.most_connected.slice(0, 8).map((n) => (
                  <li key={n.id} className="flex flex-col gap-1 text-xs">
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-foreground">{n.name}</span>
                      <span className="tabular-nums text-muted-foreground">{n.degree}</span>
                    </span>
                    <span className="h-1 overflow-hidden rounded-pill bg-surface-raised" aria-hidden="true">
                      <span className="block h-full origin-left rounded-pill bg-live transition-transform duration-large ease-enter" style={{ transform: `scaleX(${n.degree / topDegree})` }} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          {stats && stats.largest_communities.length > 0 && (
            <Panel title="Largest communities" term="community">
              <ul className="flex flex-col gap-2 text-xs">
                {stats.largest_communities.slice(0, 5).map((c) => (
                  <li key={c.id} className="flex items-start justify-between gap-3">
                    <span className="text-muted-foreground">{c.top_entities.slice(0, 4).join(', ')}</span>
                    <Badge variant="outline">{c.size}</Badge>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
