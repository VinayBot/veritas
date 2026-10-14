import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, ChevronDown, Cpu, Settings2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { useModelsStore } from '@/store/models-store'
import type { ChatModel } from '@/lib/api/types'
import { modelMeta, modelName } from '@/lib/format'
import { cn } from '@/lib/utils'

export function OllamaDown({ error, fix }: { error: string | null; fix: string | null }) {
  return (
    <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-xs" role="alert" data-testid="ollama-down">
      <p className="font-medium text-foreground">Ollama is not running, so no local model can be listed or used.</p>
      <p className="mt-1 text-muted-foreground">
        Start it in a terminal: <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-foreground">ollama serve</code>
        {fix && fix.includes('open') ? ' (or open the Ollama app).' : '.'}
      </p>
      {error && <code className="mt-2 block font-mono text-[10px] break-words text-muted-foreground">{error}</code>}
    </div>
  )
}

/** Switch the model that writes answers, from the models actually installed. */
export function ModelPicker({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { state, error, load, apply } = useModelsStore()
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState<string | null>(null)

  useEffect(() => {
    void load()
  }, [load])
  useEffect(() => {
    if (open) void load() // "loaded" and installed models change outside the app
  }, [open, load])

  const generators = state?.chat_models.filter((m) => m.roles.generator) ?? []

  async function handlePick(model: ChatModel) {
    setPending(model.id)
    try {
      const next = await apply({ generator: model.id })
      toast.success(`Answers now come from ${modelName(model.id)}`, { description: next.budget.warning ?? undefined })
      setOpen(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not switch model')
    } finally {
      setPending(null)
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" data-testid="model-picker" className="max-w-56">
          <Cpu className="size-3.5 shrink-0 text-accent" />
          <span className="truncate">{state ? modelName(state.selection.generator) : 'Model'}</span>
          <ChevronDown className="size-3 shrink-0" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-96 p-2" align="start" data-testid="model-list">
        <p className="px-2 pt-1 pb-2 text-[11px] text-muted-foreground">
          The model that writes answers. These are the chat models installed on this machine; the change applies to your next question.
        </p>
        {error ? (
          <ErrorState error={error} compact />
        ) : !state ? (
          <LoadingState shape="lines" rows={4} label="Loading models" className="p-2" />
        ) : state.ollama.status === 'down' ? (
          <OllamaDown error={state.ollama.error} fix={state.ollama.fix} />
        ) : (
          <ul className="flex max-h-[50vh] flex-col gap-1 overflow-y-auto" data-lenis-prevent>
            {generators.map((model) => {
              const active = model.id === state.selection.generator
              return (
                <li key={model.id}>
                  <button
                    type="button"
                    disabled={pending !== null}
                    onClick={() => void handlePick(model)}
                    data-testid={`model-option-${model.name}`}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-lg border p-2.5 text-left transition-colors duration-micro',
                      active ? 'border-accent/60 bg-accent/10' : 'border-transparent hover:bg-surface-raised',
                    )}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                        {model.name}
                        {active && <Check className="size-3.5 text-success" aria-label="selected" />}
                      </span>
                      <span className="block text-[11px] text-muted-foreground">{modelMeta(model)}</span>
                    </span>
                    <span
                      className={cn('shrink-0 rounded-pill px-1.5 py-0.5 text-[10px]', model.loaded ? 'bg-live/15 text-live' : 'bg-surface text-muted-foreground')}
                      title={model.loaded ? 'In memory now: the next answer starts immediately' : 'Not in memory: the first answer waits for it to load'}
                    >
                      {model.cloud ? 'cloud' : model.loaded ? 'loaded' : pending === model.id ? 'switching…' : 'on disk'}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        {state?.budget.warning && <p className="mt-2 rounded-md bg-warning/10 p-2 text-[11px] text-warning" data-testid="budget-warning">{state.budget.warning}</p>}
        <button
          type="button"
          onClick={() => {
            setOpen(false)
            onOpenSettings()
          }}
          data-testid="open-model-settings"
          className="mt-2 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-muted-foreground transition-colors duration-micro hover:bg-surface-raised hover:text-foreground"
        >
          <Settings2 className="size-3.5" /> Judge, council, embedding and reranker models…
        </button>
      </PopoverContent>
    </Popover>
  )
}
