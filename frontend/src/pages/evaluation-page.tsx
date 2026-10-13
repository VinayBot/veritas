import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMemo } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Activity, FlaskConical, Library, Share2, ShieldCheck, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Page, PageHeader, Panel } from '@/components/ui/page'
import { EmptyState } from '@/components/ui/empty-state'
import { useCommands, type CommandPaletteItem } from '@/components/ui/command-palette'
import { QualitySection } from '@/components/evaluation/QualitySection'
import { UsageSection } from '@/components/evaluation/UsageSection'
import { GraphSection } from '@/components/evaluation/GraphSection'
import { SafetySection } from '@/components/evaluation/SafetySection'
import { CorpusSection } from '@/components/evaluation/CorpusSection'
import { useAppStore } from '@/store/app-store'
import { DURATION, EASE_ENTER, SPRING_SOFT } from '@/lib/motion'
import { cn } from '@/lib/utils'

type View = 'quality' | 'usage' | 'graph' | 'safety' | 'corpus'

const VIEWS: { id: View; label: string; icon: LucideIcon; blurb: string; needsDocument: boolean }[] = [
  { id: 'quality', label: 'Quality', icon: FlaskConical, blurb: 'Measured answer and retrieval quality per strategy, from evaluation runs on questions with known answers.', needsDocument: true },
  { id: 'usage', label: 'Usage', icon: Activity, blurb: 'What real questions looked like: volume, speed, quality and failures.', needsDocument: false },
  { id: 'graph', label: 'Knowledge graph', icon: Share2, blurb: 'The entities and relations read from the document. Ask it a question and watch the path light up.', needsDocument: true },
  { id: 'safety', label: 'Safety', icon: ShieldCheck, blurb: 'Guardrail decisions on real questions, and an attack suite to run against them.', needsDocument: false },
  { id: 'corpus', label: 'Corpus', icon: Library, blurb: 'Every document that has been ingested.', needsDocument: false },
]

export function EvaluationPage() {
  const { documentId, documentName } = useAppStore()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const reduced = useReducedMotion()
  const requested = params.get('view')
  const view = VIEWS.find((v) => v.id === requested) ?? VIEWS[0]
  const setView = (id: View) => setParams(id === 'quality' ? {} : { view: id }, { replace: true })

  const commands = useMemo<CommandPaletteItem[]>(
    () =>
      VIEWS.map((v) => ({
        id: `eval-view-${v.id}`,
        label: `Evaluation: ${v.label}`,
        group: 'Navigate',
        icon: <v.icon className="size-4" />,
        onSelect: () => navigate(v.id === 'quality' ? '/app/evaluation' : `/app/evaluation?view=${v.id}`),
      })),
    [navigate],
  )
  useCommands('evaluation', commands)

  return (
    <Page testId="evaluation-page">
      <PageHeader
        title="Evaluation"
        description={
          <>
            {view.blurb}
            {view.needsDocument && documentName && (
              <>
                {' '}
                Document: <span className="text-foreground">{documentName}</span>.
              </>
            )}
          </>
        }
      />

      <div role="tablist" aria-label="Evaluation sections" className="-mt-1 flex flex-wrap gap-1 self-start rounded-xl border border-border bg-surface p-1">
        {VIEWS.map((v) => {
          const active = v.id === view.id
          return (
            <button
              key={v.id}
              type="button"
              role="tab"
              aria-selected={active}
              data-testid={`eval-tab-${v.id}`}
              onClick={() => setView(v.id)}
              className={cn(
                'relative flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors duration-micro',
                active ? 'text-on-accent' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {active && (
                <motion.span
                  layoutId="eval-tab-pill"
                  className="absolute inset-0 rounded-lg bg-accent shadow-glow"
                  transition={reduced ? { duration: 0 } : SPRING_SOFT}
                  aria-hidden="true"
                />
              )}
              <v.icon className="relative size-4" aria-hidden="true" />
              <span className="relative">{v.label}</span>
            </button>
          )
        })}
      </div>

      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={`${view.id}-${view.needsDocument ? documentId : ''}`}
          role="tabpanel"
          aria-label={view.label}
          initial={reduced ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduced ? undefined : { opacity: 0 }}
          transition={{ duration: reduced ? 0 : DURATION.standard, ease: EASE_ENTER }}
        >
          {view.needsDocument && !documentId ? (
            <Panel>
              <EmptyState
                title="Pick a document first"
                description="This view is about one document. Upload one in Workspace, or choose one from the Corpus view."
                action={
                  <>
                    <Button size="sm" onClick={() => navigate('/app')}>
                      Go to Workspace
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setView('corpus')}>
                      Open Corpus
                    </Button>
                  </>
                }
              />
            </Panel>
          ) : view.id === 'quality' ? (
            <QualitySection documentId={documentId!} />
          ) : view.id === 'usage' ? (
            <UsageSection />
          ) : view.id === 'graph' ? (
            <GraphSection documentId={documentId!} />
          ) : view.id === 'safety' ? (
            <SafetySection />
          ) : (
            <CorpusSection />
          )}
        </motion.div>
      </AnimatePresence>
    </Page>
  )
}
