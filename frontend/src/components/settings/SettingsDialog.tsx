import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { RotateCcw, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { MetricTip } from '@/components/ui/metric-tip'
import { ProgressBar } from '@/components/ui/progress-bar'
import { OllamaDown, modelMeta } from '@/components/workspace/ModelPicker'
import { useJob } from '@/hooks/useJob'
import { startReindex } from '@/lib/api/client'
import type { ChatModel, HfModel, ModelSelection } from '@/lib/api/types'
import { bytes, modelName } from '@/lib/format'
import { useModelsStore } from '@/store/models-store'
import { cn } from '@/lib/utils'

type Role = 'generator' | 'judge' | 'chairman'

function Group({ title, tip, children }: { title: string; tip: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 font-display text-sm font-semibold text-foreground">
        <MetricTip tip={tip}>{title}</MetricTip>
      </legend>
      {children}
    </fieldset>
  )
}

function Option({
  name,
  meta,
  note,
  checked,
  disabled,
  type,
  group,
  onChange,
  testId,
}: {
  name: string
  meta: string
  note?: string
  checked: boolean
  disabled?: boolean
  type: 'radio' | 'checkbox'
  group: string
  onChange: () => void
  testId?: string
}) {
  return (
    <label
      className={cn(
        'flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 text-xs transition-colors duration-micro',
        checked ? 'border-accent/60 bg-accent/10' : 'border-border hover:bg-surface-raised',
        disabled && 'cursor-not-allowed opacity-50',
      )}
      title={disabled ? note : undefined}
      data-testid={testId}
    >
      <input type={type} name={group} checked={checked} disabled={disabled} onChange={onChange} className="mt-0.5 accent-[var(--color-accent)]" />
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-foreground">{name}</span>
        <span className="block text-muted-foreground">{meta}</span>
        {note && <span className="mt-0.5 block text-warning">{note}</span>}
      </span>
    </label>
  )
}

/** Every model choice in one place. Pairings that cannot work are disabled with the reason;
 * anything the backend still refuses is shown with its message. */
export function SettingsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { state, error, load, apply, reset } = useModelsStore()
  const [busy, setBusy] = useState(false)
  const [pendingEmbedding, setPendingEmbedding] = useState<HfModel | null>(null)
  const [reindexJobId, setReindexJobId] = useState<string | null>(null)
  const reindex = useJob(reindexJobId, (job) => {
    if (job.status === 'done') toast.success(`Re-indexed ${String(job.result?.documents ?? 0)} document(s)`)
    else if (job.status === 'failed') toast.error(job.error ?? 'Re-index failed')
    setReindexJobId(null)
    void load()
  })

  useEffect(() => {
    if (open) void load()
  }, [open, load])

  async function change(changes: Partial<Omit<ModelSelection, 'guard'>>, done: string) {
    setBusy(true)
    try {
      await apply(changes)
      toast.success(done)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'That selection was refused')
    } finally {
      setBusy(false)
    }
  }

  const chat = state?.chat_models ?? []
  const down = state?.ollama.status === 'down'

  const roleList = (role: Role, key: keyof ChatModel['roles']) =>
    chat.map((m) => {
      const allowed = Boolean(m.roles[key])
      return (
        <Option
          key={m.id}
          group={role}
          type="radio"
          name={m.name}
          meta={modelMeta(m)}
          note={!allowed ? m.roles.notes.join(' ') || 'Not suitable for this role.' : role === 'judge' ? m.roles.notes.find((n) => n.startsWith('Under')) : undefined}
          checked={state!.selection[role] === m.id}
          disabled={!allowed || busy}
          testId={`${role}-option-${m.name}`}
          onChange={() => void change({ [role]: m.id }, `${role === 'generator' ? 'Generator' : role === 'judge' ? 'Judge' : 'Chairman'} set to ${m.name}`)}
        />
      )
    })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-3xl" data-testid="settings-dialog" data-lenis-prevent>
        <DialogHeader>
          <DialogTitle>Models</DialogTitle>
          <DialogDescription>
            Which model does which job. Changes apply to the next question or run; nothing restarts. Defaults come from <code>.env</code>.
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <ErrorState error={error} action={<Button size="sm" variant="outline" onClick={() => void load()}>Retry</Button>} />
        ) : !state ? (
          <LoadingState shape="table" rows={6} label="Loading models" />
        ) : (
          <div className="flex flex-col gap-6">
            {down && <OllamaDown error={state.ollama.error} fix={state.ollama.fix} />}

            {state.budget.warning && (
              <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs text-foreground" data-testid="budget-warning">
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" />
                <span>{state.budget.warning}</span>
              </div>
            )}
            {!state.budget.warning && !down && (
              <p className="text-xs text-muted-foreground">
                Selected chat models need about {bytes(state.budget.selected_bytes)} of the {bytes(state.budget.budget_bytes)} budgeted on the{' '}
                {state.budget.tier} tier ({state.budget.basis}).
              </p>
            )}

            {state.index.stale_count > 0 && (
              <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-xs" role="alert" data-testid="index-mismatch">
                <p className="font-medium text-foreground">
                  {state.index.stale_count} document{state.index.stale_count === 1 ? ' was' : 's were'} indexed with a different embedding model.
                </p>
                <p className="mt-1 text-muted-foreground">
                  Until re-indexed with {modelName(state.index.active_embedding_model)}, questions about them are refused rather than answered from
                  mismatched vectors. Re-indexing re-embeds {state.index.stale_chunks.toLocaleString()} existing chunks; the text is not re-parsed.
                </p>
                {reindex.active ? (
                  <div className="mt-2 flex flex-col gap-1">
                    <ProgressBar value={reindex.progress} label="Re-indexing" tone="live" />
                    <div className="flex items-center justify-between text-muted-foreground">
                      <span>{reindex.message}</span>
                      <button type="button" className="underline" onClick={reindex.cancel}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <Button size="sm" className="mt-2" data-testid="reindex-button" onClick={() => void startReindex().then((r) => setReindexJobId(r.job_id)).catch((e) => toast.error(String(e.message ?? e)))}>
                    Re-index now
                  </Button>
                )}
              </div>
            )}

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <Group title="Generator" tip="Writes the answers you read.">
                {roleList('generator', 'generator')}
              </Group>
              <Group title="Judge" tip="Scores answers for faithfulness, relevancy and correctness. A different, stronger model than the generator gives a more independent opinion.">
                {roleList('judge', 'judge')}
              </Group>
              <Group title="Council roster" tip="Models that each answer independently in the Council strategy, then review one another. Needs at least two.">
                {chat.map((m) => {
                  const on = state.selection.council.includes(m.id)
                  return (
                    <Option
                      key={m.id}
                      group="council"
                      type="checkbox"
                      name={m.name}
                      meta={modelMeta(m)}
                      note={!m.roles.council_member ? m.roles.notes.join(' ') : undefined}
                      checked={on}
                      disabled={!m.roles.council_member || busy}
                      testId={`council-option-${m.name}`}
                      onChange={() =>
                        void change(
                          { council: on ? state.selection.council.filter((id) => id !== m.id) : [...state.selection.council, m.id] },
                          on ? `${m.name} left the council` : `${m.name} joined the council`,
                        )
                      }
                    />
                  )
                })}
                {state.selection.council.length < 2 && <p className="text-[11px] text-warning">With fewer than two members the Council strategy is unavailable.</p>}
              </Group>
              <Group title="Council chairman" tip="Reads every council member's answer and writes the final one.">
                {roleList('chairman', 'generator')}
              </Group>
              <Group title="Embedding model" tip="Turns text into vectors for search by meaning. Changing it makes existing indexes unusable until they are rebuilt.">
                {state.embedding_models.map((m) => (
                  <Option
                    key={m.id}
                    group="embedding"
                    type="radio"
                    name={m.name}
                    meta={m.downloaded ? `downloaded · ${bytes(m.disk_bytes) ?? 'size unknown'}${m.loaded ? ' · loaded' : ''}` : 'not downloaded — will download on first use'}
                    checked={state.selection.embedding === m.id}
                    disabled={busy}
                    testId={`embedding-option-${m.name}`}
                    onChange={() => (state.selection.embedding === m.id ? undefined : setPendingEmbedding(m))}
                  />
                ))}
              </Group>
              <Group title="Reranker" tip="Re-reads the top candidates together with the question and re-orders them. No re-index needed when it changes.">
                {state.reranker_models.map((m) => (
                  <Option
                    key={m.id}
                    group="reranker"
                    type="radio"
                    name={m.name}
                    meta={m.downloaded ? `downloaded · ${bytes(m.disk_bytes) ?? 'size unknown'}${m.loaded ? ' · loaded' : ''}` : 'not downloaded — will download on first use'}
                    checked={state.selection.reranker === m.id}
                    disabled={busy}
                    onChange={() => void change({ reranker: m.id }, `Reranker set to ${m.name}`)}
                  />
                ))}
              </Group>
            </div>

            <div className="flex justify-end">
              <Button variant="outline" size="sm" disabled={busy} onClick={() => void reset().then(() => toast.success('Back to the .env defaults'))}>
                <RotateCcw className="size-3.5" /> Reset to defaults
              </Button>
            </div>
          </div>
        )}

        <ConfirmDialog
          open={pendingEmbedding !== null}
          onOpenChange={(o) => !o && setPendingEmbedding(null)}
          title="Change the embedding model?"
          description={
            <>
              Switching to <span className="font-medium text-foreground">{pendingEmbedding?.name}</span> makes every existing index unusable, because
              vectors from two models cannot be compared.
            </>
          }
          cost={
            <>
              {state?.index.ready_documents ?? 0} document(s) will need re-indexing before they can be asked about again
              {pendingEmbedding && !pendingEmbedding.downloaded ? ', and the model will be downloaded first' : ''}. Until then questions are refused, not
              answered from the wrong vectors.
            </>
          }
          confirmLabel="Switch embedding model"
          destructive
          busy={busy}
          onConfirm={() => {
            const target = pendingEmbedding
            setPendingEmbedding(null)
            if (target) void change({ embedding: target.id }, `Embedding model set to ${target.name}`)
          }}
        />
      </DialogContent>
    </Dialog>
  )
}
