import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Panel } from '@/components/ui/page'
import { StatCard } from '@/components/ui/stat-card'
import { DataTable, type Column } from '@/components/ui/data-table'
import { EmptyState, ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { listDocuments } from '@/lib/api/client'
import type { DocumentListResponse, DocumentSummary } from '@/lib/api/types'
import { compact, dateTime, relativeTime } from '@/lib/format'
import { useAppStore } from '@/store/app-store'

const STATUS_VARIANT: Record<DocumentSummary['status'], 'success' | 'outline' | 'warning' | 'destructive'> = {
  queued: 'outline',
  running: 'warning',
  ready: 'success',
  failed: 'destructive',
  cancelled: 'outline',
}

/** Every document the backend holds. Picking one makes it the working document everywhere. */
export function CorpusSection() {
  const navigate = useNavigate()
  const { documentId, setDocument } = useAppStore()
  const [corpus, setCorpus] = useState<DocumentListResponse | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(() => {
    listDocuments({ limit: 200 })
      .then((data) => {
        setCorpus(data)
        setError(null)
      })
      .catch(setError)
  }, [])
  useEffect(load, [load])

  const docs = corpus?.documents ?? []
  const shown = docs.length
  const ready = docs.filter((d) => d.status === 'ready').length
  const chunks = docs.reduce((sum, d) => sum + (d.chunk_count ?? 0), 0)
  const partial = corpus !== null && corpus.total > shown

  const columns: Column<DocumentSummary>[] = [
    { key: 'name', header: 'Document', sortValue: (d) => d.filename, render: (d) => <span className="font-medium">{d.filename}</span> },
    { key: 'status', header: 'Status', sortValue: (d) => d.status, render: (d) => <Badge variant={STATUS_VARIANT[d.status]}>{d.status}</Badge> },
    { key: 'chunks', header: 'Chunks', term: 'chunk', align: 'right', sortValue: (d) => d.chunk_count, render: (d) => d.chunk_count ?? '—' },
    { key: 'strategy', header: 'Chunking', sortValue: (d) => d.chunk_strategy, render: (d) => d.chunk_strategy ?? '—' },
    { key: 'entities', header: 'Entities', align: 'right', sortValue: (d) => d.graph_entity_count, render: (d) => d.graph_entity_count ?? '—' },
    { key: 'ingested', header: 'Ingested', sortValue: (d) => d.created_at, render: (d) => <span title={dateTime(d.created_at)}>{relativeTime(d.created_at)}</span> },
    {
      key: 'active',
      header: '',
      render: (d) =>
        d.id === documentId ? (
          <Badge variant="glow">active</Badge>
        ) : (
          <Button
            size="xs"
            variant="outline"
            onClick={(e) => {
              e.stopPropagation()
              setDocument(d.id, d.filename)
            }}
          >
            Use
          </Button>
        ),
    },
  ]

  return (
    <div className="flex flex-col gap-6" data-testid="eval-corpus">
      {error ? (
        <ErrorState error={error} action={<Button size="sm" variant="outline" onClick={load}>Retry</Button>} />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Documents" loading={corpus === null} value={corpus ? compact(corpus.total) : undefined} caption={corpus ? `${ready} ready${partial ? ` of the newest ${shown}` : ''}` : undefined} testId="dashboard-kpi-documents" />
            <StatCard
              label="Chunks indexed"
              term="chunk"
              loading={corpus === null}
              value={corpus ? compact(chunks) : undefined}
              caption={partial ? `across the newest ${shown} documents` : 'across the corpus'}
            />
            <StatCard
              label="Last ingest"
              loading={corpus === null}
              value={docs[0] ? relativeTime(docs[0].created_at) : undefined}
              emptyLabel="Nothing ingested yet"
              caption={docs[0]?.filename}
            />
            <StatCard
              label="Failed ingests"
              loading={corpus === null}
              value={corpus ? docs.filter((d) => d.status === 'failed').length : undefined}
              caption={partial ? `in the newest ${shown}` : undefined}
            />
          </div>

          <Panel title="Corpus" description="Every document the backend holds, newest first. Pick one to make it the working document.">
            {corpus === null ? (
              <LoadingState shape="table" rows={6} label="Loading corpus" />
            ) : (
              <DataTable
                caption="Documents in the corpus"
                columns={columns}
                rows={docs}
                rowKey={(d) => d.id}
                initialSort={{ key: 'ingested', direction: 'desc' }}
                testId="corpus-table"
                empty={
                  <EmptyState
                    title="No documents yet"
                    description="Upload a document, or load the bundled sample, to give the system something to work with."
                    action={<Button size="sm" onClick={() => navigate('/app')}>Go to Workspace</Button>}
                  />
                }
              />
            )}
          </Panel>
        </>
      )}
    </div>
  )
}
