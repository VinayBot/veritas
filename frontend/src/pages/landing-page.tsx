import { Link } from 'react-router-dom'
import {
  ArrowRight,
  MessageSquare,
  LayoutDashboard,
  Workflow,
  Share2,
  FlaskConical,
  ShieldAlert,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { TiltCard } from '@/components/ui/tilt-card'
import { ThemeToggle } from '@/components/ui/theme-toggle'

const FEATURES = [
  {
    icon: MessageSquare,
    title: 'Agentic RAG',
    description:
      'A LangGraph state machine — planner, rewriter, retriever, critic, synthesizer, verifier — with hybrid and graph modes as simpler alternatives, plus an opt-in multi-model council vote.',
  },
  {
    icon: LayoutDashboard,
    title: 'Honest quality scores',
    description:
      'Every answer carries a real LLM-judged quality report, labelled Estimated or Verified depending on whether ground truth exists — never a hardcoded number.',
  },
  {
    icon: Workflow,
    title: 'Live architecture trace',
    description:
      'The pipeline diagram animates from real backend trace events over a WebSocket — no timers, no synthetic pulses.',
  },
  {
    icon: Share2,
    title: 'GraphRAG knowledge graph',
    description:
      'Entities and relations extracted at ingestion via NER + LLM triple extraction, with Louvain community detection.',
  },
  {
    icon: FlaskConical,
    title: 'Self-benchmarking',
    description:
      'A real 5-candidate chunking tournament profiles every document and suggests a better config, backed by a full retrieval/agent benchmark suite.',
  },
  {
    icon: ShieldAlert,
    title: '3-layer guardrails',
    description:
      'Regex heuristics, a prompt-injection classifier, and Llama Guard, measured against a 42-attack red-team corpus with a published block rate.',
  },
]

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <span className="font-display text-lg font-semibold tracking-tight">Veritas</span>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <Button asChild size="sm">
            <Link to="/app">
              Open Workspace <ArrowRight className="size-3.5" />
            </Link>
          </Button>
        </div>
      </header>

      <section className="mx-auto flex max-w-3xl flex-col items-center gap-6 px-6 py-24 text-center">
        <span className="rounded-full border border-accent/30 bg-accent/10 px-3 py-1 text-xs font-medium text-accent-soft">
          Free and local by default — no API key required
        </span>
        <h1 className="font-display text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
          An adaptive RAG platform that shows its work
        </h1>
        <p className="max-w-xl text-balance text-muted-foreground">
          Veritas ingests a document, profiles it, runs a real tournament to pick a chunking
          strategy, answers questions with a verified, cited agentic pipeline, and reports every
          quality score honestly — Estimated when there's no ground truth, Verified when there
          is.
        </p>
        <div className="flex gap-3">
          <Button asChild size="lg">
            <Link to="/app">
              Try it now <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl grid-cols-1 gap-5 px-6 pb-24 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f) => (
          <TiltCard key={f.title} className="flex flex-col gap-3">
            <f.icon className="size-6 text-accent-soft" aria-hidden="true" />
            <h2 className="font-display text-base font-semibold text-foreground">{f.title}</h2>
            <p className="text-sm text-muted-foreground">{f.description}</p>
          </TiltCard>
        ))}
      </section>

      <footer className="mx-auto max-w-6xl px-6 pb-10 text-center text-xs text-muted-foreground">
        Built with a local-first stack: FastAPI, LangGraph, Ollama, ChromaDB, and React.
      </footer>
    </div>
  )
}
