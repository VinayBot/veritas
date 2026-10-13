import {
  BarChart3,
  Database,
  FlaskConical,
  LayoutDashboard,
  Scissors,
  Share2,
  ShieldAlert,
} from 'lucide-react'

export const EVAL_SECTIONS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'retrieval', label: 'Retrieval', icon: BarChart3 },
  { id: 'chunking-advisor', label: 'Chunking Advisor', icon: Scissors },
  { id: 'guardrails', label: 'Guardrails / Red-team', icon: ShieldAlert },
  { id: 'datasets', label: 'Datasets', icon: Database },
  { id: 'benchmarks', label: 'Benchmarks', icon: FlaskConical },
  { id: 'knowledge-graph', label: 'Knowledge Graph', icon: Share2 },
] as const

export type EvalSectionId = (typeof EVAL_SECTIONS)[number]['id']

/** EV-2: in-page navigation. Horizontal/bottom bar under 768px (EV-9), vertical rail above
 * it — both just scroll the single page to the matching section (data-testid used by the
 * EV-10 visual-snapshot test too). */
export function EvaluationRail({ onNavigate }: { onNavigate: (id: EvalSectionId) => void }) {
  return (
    <nav
      className="theme-eval flex gap-1 overflow-x-auto rounded-2xl border p-1.5 md:flex-col md:overflow-visible"
      style={{ borderColor: 'var(--ev-border)', background: 'var(--ev-bg-from)' }}
      aria-label="Evaluation sections"
      data-testid="evaluation-rail"
    >
      {EVAL_SECTIONS.map((section) => (
        <button
          key={section.id}
          type="button"
          title={section.label}
          onClick={() => onNavigate(section.id)}
          data-testid={`eval-rail-${section.id}`}
          className="flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition-colors hover:bg-white/10 md:w-full"
          style={{ color: 'var(--ev-text)' }}
        >
          <section.icon className="size-4 shrink-0" aria-hidden="true" />
          <span className="hidden md:inline">{section.label}</span>
        </button>
      ))}
    </nav>
  )
}
