import { useEffect, useMemo, useState } from 'react'
import { ChevronsUpDown, FileText, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EmptyState, ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { deleteDocument, listDocuments } from '@/lib/api/client'
import type { DocumentSummary } from '@/lib/api/types'
import { useAppStore } from '@/store/app-store'
import { cn } from '@/lib/utils'

const STATUS_VARIANT: Record<DocumentSummary['status'], 'success' | 'outline' | 'warning' | 'destructive'> = {
  queued: 'outline',
  running: 'warning',
  ready: 'success',
  failed: 'destructive',
  cancelled: 'outline',
}

/** Sidebar control showing the active document, opening a searchable list of every document
 * the backend has. Selecting one makes it the working document for every tab. */
export function DocumentSwitcher({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { documentId, documentName, setDocument } = useAppStore()
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<unknown>(null)
  const [filter, setFilter] = useState('')
  const [pendingDelete, setPendingDelete] = useState<DocumentSummary | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setDocs(null)
    setError(null)
    listDocuments({ limit: 200 })
      .then((data) => {
        if (cancelled) return
        setDocs(data.documents)
        setTotal(data.total)
      })
      .catch((err) => !cancelled && setError(err))
    return () => {
      cancelled = true
    }
  }, [open])

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return (docs ?? []).filter((d) => !q || d.filename.toLowerCase().includes(q) || d.id.startsWith(q))
  }, [docs, filter])

  async function handleDelete() {
    if (!pendingDelete) return
    setDeleting(true)
    try {
      const result = await deleteDocument(pendingDelete.id)
      toast.success(`Deleted "${pendingDelete.filename}" — ${result.chunks_removed} chunks removed`)
      setDocs((prev) => (prev ?? []).filter((d) => d.id !== pendingDelete.id))
      setTotal((t) => Math.max(0, t - 1))
      if (pendingDelete.id === documentId) setDocument(null, null)
      setPendingDelete(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        data-testid="document-switcher"
        className="flex w-full items-center gap-2 rounded-lg border border-border bg-surface-raised px-3 py-1 text-left text-xs transition-colors duration-micro hover:border-accent/50"
      >
        <FileText className="size-4 shrink-0 text-accent-soft" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          <span className="block text-[10px] font-medium tracking-wide text-muted-foreground uppercase">Document</span>
          <span className="block truncate font-medium text-foreground">{documentName ?? 'None selected'}</span>
        </span>
        <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
      </button>

      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Documents</DialogTitle>
            <DialogDescription>
              {docs ? `${total} in the corpus${total > docs.length ? ` — showing the newest ${docs.length}` : ''}.` : 'Loading the corpus…'}{' '}
              The selected document is what every tab works with.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by file name"
            aria-label="Filter documents"
          />
          <div className="max-h-[50vh] overflow-y-auto" data-lenis-prevent>
            {error ? (
              <ErrorState error={error} />
            ) : docs === null ? (
              <LoadingState shape="table" rows={5} label="Loading documents" />
            ) : visible.length === 0 ? (
              <EmptyState title={docs.length === 0 ? 'No documents yet' : 'Nothing matches that filter'} description={docs.length === 0 ? 'Upload one in Workspace to get started.' : undefined} />
            ) : (
              <ul className="flex flex-col gap-1">
                {visible.map((d) => (
                  <li key={d.id} className="flex items-center gap-2">
                    <button
                      type="button"
                      data-testid={`document-option-${d.id}`}
                      onClick={() => {
                        setDocument(d.id, d.filename)
                        onOpenChange(false)
                      }}
                      className={cn(
                        'flex min-w-0 flex-1 items-center gap-3 rounded-lg border px-3 py-1 text-left text-xs transition-colors duration-micro',
                        d.id === documentId ? 'border-accent/50 bg-accent/10' : 'border-transparent hover:bg-surface-raised',
                      )}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-foreground">{d.filename}</span>
                        <span className="block text-muted-foreground">
                          {new Date(d.created_at + (d.created_at.endsWith('Z') ? '' : 'Z')).toLocaleString()} · {d.chunk_count ?? 0} chunks ·{' '}
                          {d.graph_entity_count ?? 0} entities
                        </span>
                      </span>
                      <Badge variant={STATUS_VARIANT[d.status]}>{d.status}</Badge>
                    </button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Delete ${d.filename}`}
                      onClick={() => setPendingDelete(d)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title="Delete this document?"
        description={
          <>
            <span className="font-medium text-foreground">{pendingDelete?.filename}</span> will be removed along with its chunks,
            vectors, keyword-index entries, graph relations and the uploaded file.
          </>
        }
        cost="This cannot be undone. Evaluation runs and chat reports that reference it are kept."
        confirmLabel="Delete"
        destructive
        busy={deleting}
        onConfirm={() => void handleDelete()}
      />
    </>
  )
}
