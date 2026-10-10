import { useCallback, useEffect, useMemo, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { StateMessage, type ComponentStatus } from '@/components/ui/state-message'
import { useAppStore } from '@/store/app-store'
import { useDocumentStatus } from '@/hooks/useDocumentStatus'
import { getGraph, ApiError } from '@/lib/api/client'
import type { GraphNode } from '@/lib/api/types'

const COMMUNITY_COLORS = [
  '#8b5cf6',
  '#34d399',
  '#fbbf24',
  '#f87171',
  '#60a5fa',
  '#f472b6',
  '#2dd4bf',
  '#fb923c',
]

export function KnowledgeGraphPage() {
  const { documentId } = useAppStore()
  const { doc } = useDocumentStatus(documentId)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<ComponentStatus>('loading')
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [links, setLinks] = useState<{ source: string; target: string; predicate: string | null }[]>(
    [],
  )
  const [selected, setSelected] = useState<GraphNode | null>(null)

  const load = useCallback(async (q?: string) => {
    if (!documentId) return
    setStatus('loading')
    try {
      const data = await getGraph(documentId, q, 2)
      setNodes(data.nodes)
      setLinks(
        data.edges.map((e) => ({ source: e.source, target: e.target, predicate: e.predicate })),
      )
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

  const graphData = useMemo(
    () => ({
      nodes: nodes.map((n) => ({ ...n })),
      links: links.map((l) => ({ ...l })),
    }),
    [nodes, links],
  )

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
              description="No entities found for this document or query."
            />
          </div>
        )}
        {status === 'success' && (
          <ForceGraph2D
            graphData={graphData}
            nodeId="id"
            nodeLabel={(n) => `${(n as GraphNode).name} (${(n as GraphNode).label})`}
            nodeColor={(n) => {
              const community = (n as GraphNode).community
              return community === null || community === undefined
                ? '#8d8aa3'
                : COMMUNITY_COLORS[community % COMMUNITY_COLORS.length]
            }}
            linkLabel={(l) => (l as { predicate: string | null }).predicate ?? ''}
            linkColor={() => 'rgba(141, 138, 163, 0.4)'}
            backgroundColor="transparent"
            onNodeClick={(n) => setSelected(n as GraphNode)}
          />
        )}
      </div>

      {selected && (
        <div className="rounded-lg border border-border bg-surface-raised p-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="font-medium text-foreground">{selected.name}</span>
            <Badge variant="outline">{selected.label}</Badge>
            {selected.community !== null && <Badge variant="glow">community {selected.community}</Badge>}
          </div>
          <p className="text-xs text-muted-foreground">
            Mentions: {selected.mentions.join(', ') || '—'}
          </p>
          <p className="text-xs text-muted-foreground">
            Appears in {selected.doc_ids.length} document{selected.doc_ids.length === 1 ? '' : 's'}
          </p>
        </div>
      )}
    </div>
  )
}
