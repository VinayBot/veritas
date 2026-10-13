import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { Search, Sparkles } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { StateMessage, type ComponentStatus } from '@/components/ui/state-message'
import { useAppStore } from '@/store/app-store'
import { useDocumentStatus } from '@/hooks/useDocumentStatus'
import { getGraph, ApiError } from '@/lib/api/client'
import type { GraphEdge, GraphNode } from '@/lib/api/types'

const KnowledgeGraphCanvas = lazy(() =>
  // The three.js chunk (and its own, separately heavy dependency) only loads once this
  // page's graph panel actually mounts (KG-8) — not on every app bundle load.
  import('@/components/knowledge-graph/KnowledgeGraphCanvas').then((m) => ({
    default: m.KnowledgeGraphCanvas,
  })),
)

export function KnowledgeGraphPage() {
  const { documentId } = useAppStore()
  const { doc } = useDocumentStatus(documentId)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<ComponentStatus>('loading')
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [edges, setEdges] = useState<GraphEdge[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const [askQuestion, setAskQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [highlightSequence, setHighlightSequence] = useState<string[] | undefined>(undefined)
  const [highlightStep, setHighlightStep] = useState<string | null>(null)

  const load = useCallback(async (q?: string) => {
    if (!documentId) return
    setStatus('loading')
    try {
      const data = await getGraph(documentId, q, 2)
      setNodes(data.nodes)
      setEdges(data.edges)
      setStatus(data.nodes.length === 0 ? 'empty' : 'success')
    } catch (err) {
      setStatus('error')
      if (err instanceof ApiError) console.error(err.message)
    }
  }, [documentId])

  // Re-fetches whenever enrichment_status changes, not just on mount — graph extraction runs
  // as a background phase that can still be in flight when this page is first visited (the
  // document only needs to be "ready" for chat, not fully enriched), so an empty graph that
  // was simply "not built yet" a moment ago shows up once extraction actually finishes.
  useEffect(() => {
    void load()
  }, [load, doc?.enrichment_status])

  const selectedNode = useMemo(() => nodes.find((n) => n.id === selectedId) ?? null, [nodes, selectedId])

  // KG-5: "Ask the graph" runs the EXISTING graph-mode query (GET /graph/{id}?query=...) —
  // the same real traversal the search box below already uses — then highlights its real
  // linked entities and traversal-path nodes on the torus in sequence.
  async function handleAskGraph(e: React.FormEvent) {
    e.preventDefault()
    if (!documentId || !askQuestion.trim()) return
    setAsking(true)
    setHighlightStep(null)
    try {
      const data = await getGraph(documentId, askQuestion, 2)
      const linkedIds = (data.linked_entities ?? []).map((n) => n.id)
      const pathIds = data.nodes.map((n) => n.id).filter((id) => !linkedIds.includes(id))
      const sequence = [...linkedIds, ...pathIds]
      if (sequence.length === 0) {
        setHighlightSequence(undefined)
      } else {
        setHighlightSequence(sequence)
      }
    } catch (err) {
      if (err instanceof ApiError) console.error(err.message)
    } finally {
      setAsking(false)
    }
  }

  if (!documentId) {
    return (
      <div className="flex h-screen items-center justify-center p-6">
        <StateMessage status="empty" description="Upload a document in Workspace first." />
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col gap-4 p-6">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold text-foreground">Knowledge Graph</h1>
          <p className="text-sm text-muted-foreground">
            Entities and relations extracted by GraphRAG at ingestion — real NER + LLM triple
            extraction, not a mock.
          </p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void load(query || undefined)
          }}
          className="flex items-center gap-2"
        >
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search entities, e.g. 'vacation'"
            className="w-64"
          />
          <button type="submit" className="rounded-md border border-border p-2 text-muted-foreground hover:text-foreground">
            <Search className="size-4" />
          </button>
        </form>
      </header>

      <div className="relative flex-1 overflow-hidden rounded-lg border border-border bg-surface">
        {status === 'loading' && (
          <div className="absolute inset-0 flex items-center justify-center">
            <StateMessage status="empty" title="Loading graph..." />
          </div>
        )}
        {status === 'error' && (
          <div className="absolute inset-0 flex items-center justify-center">
            <StateMessage status="error" />
          </div>
        )}
        {status === 'empty' && (
          <div className="absolute inset-0 flex items-center justify-center">
            <StateMessage
              status="empty"
              title="Ingest a document to grow the graph"
              description="No entities found yet for this document or query."
            />
          </div>
        )}
        {status === 'success' && (
          <Suspense
            fallback={
              <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
                Loading graph renderer...
              </div>
            }
          >
            <KnowledgeGraphCanvas
              nodes={nodes}
              edges={edges}
              onSelectEntity={(entity) => setSelectedId(entity?.id ?? null)}
              highlightSequence={highlightSequence}
              onHighlightStep={setHighlightStep}
            />
          </Suspense>
        )}

        {status === 'success' && (
          <form
            onSubmit={(e) => void handleAskGraph(e)}
            className="absolute top-3 left-1/2 flex w-full max-w-md -translate-x-1/2 items-center gap-2 rounded-full border border-border bg-surface/95 px-3 py-1.5 shadow-md backdrop-blur"
            data-testid="ask-the-graph-form"
          >
            <Sparkles className="size-4 shrink-0 text-accent" />
            <input
              value={askQuestion}
              onChange={(e) => setAskQuestion(e.target.value)}
              placeholder="Ask the graph..."
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <Button type="submit" size="sm" disabled={asking || !askQuestion.trim()}>
              {asking ? 'Asking...' : 'Ask'}
            </Button>
          </form>
        )}
        {highlightStep && (
          <p className="absolute top-14 left-1/2 -translate-x-1/2 rounded-full bg-surface/90 px-2.5 py-1 text-xs text-muted-foreground backdrop-blur">
            Lighting up: {nodes.find((n) => n.id === highlightStep)?.name ?? highlightStep}
          </p>
        )}
      </div>

      {selectedNode && (
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="font-medium text-foreground">{selectedNode.name}</span>
            <Badge variant="outline">{selectedNode.label}</Badge>
            {selectedNode.community !== null && (
              <Badge variant="glow">community {selectedNode.community}</Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Mentions: {selectedNode.mentions.join(', ') || '—'}
          </p>
          <p className="text-xs text-muted-foreground">
            Appears in {selectedNode.doc_ids.length} document{selectedNode.doc_ids.length === 1 ? '' : 's'}
          </p>
        </div>
      )}
    </div>
  )
}
