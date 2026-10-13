import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  Bell,
  Check,
  FlaskConical,
  Loader2,
  Settings,
  ShieldAlert,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { StateMessage, type ComponentStatus } from '@/components/ui/state-message'
import { useAppStore } from '@/store/app-store'
import {
  generateDataset,
  runBenchmark,
  runRedteam,
  listBenchmarkRuns,
  getAdvisor,
  runAdvisor,
  decideAdvisor,
  getGraph,
  ApiError,
} from '@/lib/api/client'
import type {
  AdvisorResponse,
  BenchmarkRunResponse,
  GenerateDatasetResponse,
  GraphEdge,
  GraphNode,
  RedTeamRunResponse,
} from '@/lib/api/types'
import { EvalKpiCard } from '@/components/evaluation/EvalKpiCard'
const RetrievalQualityChart = lazy(() =>
  // echarts is one of the heaviest deps in this app (same precedent as component-showcase.tsx's
  // lazy-loading of it) — this is the only place on this page that imports it, so it should
  // only load once this chart actually renders, not on every Evaluation page visit.
  import('@/components/evaluation/RetrievalQualityChart').then((m) => ({
    default: m.RetrievalQualityChart,
  })),
)
import { ChunkingStrategyTable, candidatesToStrategyRows } from '@/components/evaluation/ChunkingStrategyTable'
import { RunHealthPanel } from '@/components/evaluation/RunHealthPanel'
import { EvaluationRail, EVAL_SECTIONS, type EvalSectionId } from '@/components/evaluation/EvaluationRail'

const KnowledgeGraphCanvas = lazy(() =>
  import('@/components/knowledge-graph/KnowledgeGraphCanvas').then((m) => ({
    default: m.KnowledgeGraphCanvas,
  })),
)

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`
}

/** Delta vs the IMMEDIATELY PREVIOUS real run — undefined (not 0) when there isn't one (G1). */
function deltaFor(current: number, previous: number | undefined): { direction: 'up' | 'down'; label: string } | undefined {
  if (previous === undefined) return undefined
  const diff = current - previous
  if (Math.abs(diff) < 0.0005) return undefined
  return { direction: diff > 0 ? 'up' : 'down', label: `${diff > 0 ? '+' : ''}${(diff * 100).toFixed(1)}pp vs last run` }
}

export function EvaluationPage() {
  const { documentId } = useAppStore()
  const sectionRefs = useRef<Partial<Record<EvalSectionId, HTMLElement | null>>>({})

  const [generating, setGenerating] = useState(false)
  const [dataset, setDataset] = useState<GenerateDatasetResponse | null>(null)
  const [benchmarking, setBenchmarking] = useState(false)
  const [runs, setRuns] = useState<BenchmarkRunResponse[]>([])
  const [runsLoaded, setRunsLoaded] = useState(false)
  const [redteamRunning, setRedteamRunning] = useState(false)
  const [redteam, setRedteam] = useState<RedTeamRunResponse | null>(null)

  const [advisor, setAdvisor] = useState<AdvisorResponse | null>(null)
  const [advisorStatus, setAdvisorStatus] = useState<ComponentStatus>('empty')
  const [advisorRunning, setAdvisorRunning] = useState(false)
  const [deciding, setDeciding] = useState<'accept' | 'ignore' | null>(null)

  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([])
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([])
  const [gearOpen, setGearOpen] = useState(false)

  const loadRuns = useCallback(async () => {
    if (!documentId) return
    try {
      const data = await listBenchmarkRuns(documentId)
      setRuns(data.runs)
    } catch {
      // honest empty state below handles this — no history endpoint failure should block the page
    } finally {
      setRunsLoaded(true)
    }
  }, [documentId])

  const loadAdvisor = useCallback(async () => {
    if (!documentId) return
    setAdvisorStatus('loading')
    try {
      const data = await getAdvisor(documentId)
      setAdvisor(data)
      setAdvisorStatus('success')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'no_recommendation') {
        setAdvisor(null)
        setAdvisorStatus('empty')
      } else {
        setAdvisorStatus('error')
      }
    }
  }, [documentId])

  useEffect(() => {
    void loadRuns()
    void loadAdvisor()
  }, [loadRuns, loadAdvisor])

  useEffect(() => {
    if (!documentId) return
    getGraph(documentId)
      .then((data) => {
        setGraphNodes(data.nodes)
        setGraphEdges(data.edges)
      })
      .catch(() => {})
  }, [documentId])

  async function handleRedteam() {
    setRedteamRunning(true)
    try {
      const data = await runRedteam()
      setRedteam(data)
      toast.success(`Red-team: ${pct(data.block_rate)} blocked`)
    } catch {
      toast.error('Red-team run failed')
    } finally {
      setRedteamRunning(false)
    }
  }

  async function handleGenerate() {
    if (!documentId) return
    setGenerating(true)
    try {
      const data = await generateDataset(documentId, 20)
      setDataset(data)
      toast.success(`Generated ${data.item_count} eval items (v${data.version})`)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Dataset generation failed')
    } finally {
      setGenerating(false)
    }
  }

  async function handleBenchmark() {
    if (!documentId) return
    setBenchmarking(true)
    try {
      const data = await runBenchmark({ document_id: documentId, dataset_target_size: 10 })
      toast.success(`Benchmark complete — recommended: ${data.recommended_config ?? 'none'}`)
      await loadRuns()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Benchmark run failed')
    } finally {
      setBenchmarking(false)
    }
  }

  async function handleRunAdvisor() {
    if (!documentId) return
    setAdvisorRunning(true)
    try {
      const data = await runAdvisor(documentId)
      setAdvisor(data)
      setAdvisorStatus('success')
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Advisor run failed')
    } finally {
      setAdvisorRunning(false)
    }
  }

  async function handleDecision(decision: 'accept' | 'ignore') {
    if (!documentId) return
    setDeciding(decision)
    try {
      const data = await decideAdvisor(documentId, decision)
      setAdvisor(data)
      toast.success(decision === 'accept' ? 'Document re-indexed with the suggested config' : 'Recommendation ignored')
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Decision failed')
    } finally {
      setDeciding(null)
    }
  }

  const latest = runs[runs.length - 1]
  const previous = runs[runs.length - 2]
  const latestConfig = latest?.config_results.find((c) => c.name === latest.recommended_config) ?? latest?.config_results[0]
  const previousConfig = previous?.config_results.find((c) => c.name === previous.recommended_config) ?? previous?.config_results[0]

  const strategyRows = useMemo(
    () => (advisor ? candidatesToStrategyRows(advisor.candidates.length > 0 ? advisor.candidates : [advisor.baseline, advisor.suggested]) : []),
    [advisor],
  )

  const hasGateFailure = !!latestConfig && !latestConfig.passes_hard_gates
  const [bellOpen, setBellOpen] = useState(false)

  function scrollTo(id: EvalSectionId) {
    sectionRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (!documentId) {
    return (
      <div className="flex h-screen items-center justify-center p-6">
        <StateMessage status="empty" description="Upload a document in Workspace first." />
      </div>
    )
  }

  return (
    <div className="theme-eval flex h-screen flex-col bg-black md:flex-row" style={{ background: '#0d0b24' }}>
      <div className="order-2 shrink-0 p-3 md:order-1 md:w-56">
        <EvaluationRail onNavigate={scrollTo} />
      </div>

      <div className="order-1 flex-1 overflow-y-auto p-4 md:order-2" data-lenis-prevent>
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[color:var(--ev-fill)] font-display text-sm font-semibold text-white">
              V
            </span>
            <div>
              <h1 className="font-display text-xl font-semibold" style={{ color: 'var(--ev-text)' }}>
                Evaluation
              </h1>
              <p className="text-xs" style={{ color: 'var(--ev-muted)' }}>
                A real synthetic eval set, scored against real retrieval/agent configs — every number comes from an actual run.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                type="button"
                aria-label="Notifications"
                onClick={() => setBellOpen((v) => !v)}
                className="relative flex size-9 items-center justify-center rounded-full border"
                style={{ borderColor: 'var(--ev-border)', color: 'var(--ev-text)' }}
              >
                <Bell className="size-4" />
                {hasGateFailure && (
                  <span className="absolute top-1 right-1 size-2 rounded-full bg-[#f87171]" aria-hidden="true" />
                )}
              </button>
              {bellOpen && (
                <div
                  className="absolute right-0 z-20 mt-2 w-56 rounded-lg border p-3 text-xs shadow-xl"
                  style={{ background: 'var(--ev-bg-from)', borderColor: 'var(--ev-border)', color: 'var(--ev-text)' }}
                  data-testid="eval-notifications"
                >
                  {hasGateFailure ? (
                    <p>Last benchmark run failed a hard gate (faithfulness/safety/latency).</p>
                  ) : (
                    <p style={{ color: 'var(--ev-muted)' }}>No alerts — last run passed its hard gates.</p>
                  )}
                </div>
              )}
            </div>
            <div className="relative">
              <button
                type="button"
                aria-label="Thresholds and judge model settings"
                aria-expanded={gearOpen}
                onClick={() => setGearOpen((v) => !v)}
                className="flex size-9 items-center justify-center rounded-full border"
                style={{ borderColor: 'var(--ev-border)', color: 'var(--ev-text)' }}
              >
                <Settings className="size-4" />
              </button>
              {gearOpen && (
                <div
                  className="absolute right-0 z-20 mt-2 w-64 rounded-lg border p-3 text-xs shadow-xl"
                  style={{ background: 'var(--ev-bg-from)', borderColor: 'var(--ev-border)', color: 'var(--ev-text)' }}
                  data-testid="eval-thresholds"
                >
                  <p className="mb-2 font-medium">Hard gate thresholds (real values the backend enforces)</p>
                  <ul className="flex flex-col gap-1" style={{ color: 'var(--ev-muted)' }}>
                    <li>Faithfulness &ge; 0.85</li>
                    <li>Injection block rate &ge; 0.95</li>
                    <li>PII leaks == 0</li>
                    <li>p95 latency &le; 15,000ms</li>
                  </ul>
                </div>
              )}
            </div>
            <Button onClick={() => void handleBenchmark()} disabled={benchmarking} data-testid="run-benchmark-button">
              {benchmarking ? <Loader2 className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
              Run benchmark
            </Button>
          </div>
        </header>

        <div ref={(el) => { sectionRefs.current.overview = el }} id="overview" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <EvalKpiCard
            label="Answer faithfulness"
            value={latestConfig ? latestConfig.faithfulness.toFixed(2) : undefined}
            delta={latestConfig && previousConfig ? deltaFor(latestConfig.faithfulness, previousConfig.faithfulness) : undefined}
            emptyDescription="Run a benchmark"
          />
          <EvalKpiCard
            label="Retrieval Recall@5"
            value={latestConfig ? pct(latestConfig.retrieval_metrics.recall_at_5 ?? 0) : undefined}
            delta={
              latestConfig && previousConfig
                ? deltaFor(latestConfig.retrieval_metrics.recall_at_5 ?? 0, previousConfig.retrieval_metrics.recall_at_5)
                : undefined
            }
            emptyDescription="Run a benchmark"
          />
          <EvalKpiCard
            label="Red-team block rate"
            value={redteam ? `${redteam.blocked_attacks}/${redteam.total_attacks}` : undefined}
            emptyDescription="Run the red-team suite"
          />
          <EvalKpiCard
            label="Median latency p50"
            value={latestConfig ? `${Math.round(latestConfig.p50_latency_ms)}ms` : undefined}
            delta={
              latestConfig && previousConfig
                ? deltaFor(previousConfig.p50_latency_ms, latestConfig.p50_latency_ms) // lower latency = improvement
                : undefined
            }
            emptyDescription="Run a benchmark"
          />
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="flex flex-col gap-4 lg:col-span-2">
            <section
              ref={(el) => { sectionRefs.current.retrieval = el }}
              id="retrieval"
              className="rounded-2xl border p-4"
              style={{ borderColor: 'var(--ev-border)', background: 'linear-gradient(180deg, var(--ev-bg-from), var(--ev-bg-to))' }}
            >
              <h2 className="mb-2 text-sm font-semibold" style={{ color: 'var(--ev-text)' }}>
                Retrieval quality by run
              </h2>
              {runsLoaded ? (
                <Suspense fallback={<p className="text-xs" style={{ color: 'var(--ev-muted)' }}>Loading chart...</p>}>
                  <RetrievalQualityChart runs={runs} />
                </Suspense>
              ) : (
                <p className="text-xs" style={{ color: 'var(--ev-muted)' }}>Loading...</p>
              )}
            </section>

            <section
              ref={(el) => { sectionRefs.current['chunking-advisor'] = el }}
              id="chunking-advisor"
              className="rounded-2xl border p-4"
              style={{ borderColor: 'var(--ev-border)', background: 'linear-gradient(180deg, var(--ev-bg-from), var(--ev-bg-to))' }}
            >
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold" style={{ color: 'var(--ev-text)' }}>
                  Chunking strategy performance (sorted by score)
                </h2>
                <Button size="sm" variant="outline" onClick={() => void handleRunAdvisor()} disabled={advisorRunning}>
                  {advisorRunning ? 'Running...' : 'Run advisor'}
                </Button>
              </div>
              {advisorStatus === 'loading' && <p className="text-xs" style={{ color: 'var(--ev-muted)' }}>Loading...</p>}
              {(advisorStatus === 'success' || advisorStatus === 'empty') && <ChunkingStrategyTable rows={strategyRows} />}

              {advisor && advisor.decision === null && (
                <div className="mt-3 flex items-center gap-2">
                  <p className="text-xs" style={{ color: 'var(--ev-muted)' }}>
                    Suggested: <span style={{ color: 'var(--ev-value)' }}>{advisor.suggested.chunking_strategy}</span> (+
                    {advisor.gain_ndcg_points.toFixed(1)} nDCG pts)
                  </p>
                  <Button size="sm" disabled={deciding !== null} onClick={() => void handleDecision('accept')}>
                    <Check className="size-3.5" /> Accept
                  </Button>
                  <Button size="sm" variant="outline" disabled={deciding !== null} onClick={() => void handleDecision('ignore')}>
                    <X className="size-3.5" /> Ignore
                  </Button>
                </div>
              )}
              {advisor && advisor.decision !== null && (
                <Badge variant="outline" className="mt-3">
                  decision: {advisor.decision}
                </Badge>
              )}
            </section>

            <section
              ref={(el) => { sectionRefs.current.guardrails = el }}
              id="guardrails"
              className="rounded-2xl border p-4"
              style={{ borderColor: 'var(--ev-border)', background: 'linear-gradient(180deg, var(--ev-bg-from), var(--ev-bg-to))' }}
              data-testid="safety-redteam-card"
            >
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold" style={{ color: 'var(--ev-text)' }}>
                  Guardrails / Red-team
                </h2>
                <Button size="sm" onClick={() => void handleRedteam()} disabled={redteamRunning}>
                  {redteamRunning ? <Loader2 className="size-4 animate-spin" /> : <ShieldAlert className="size-4" />}
                  Run red-team suite
                </Button>
              </div>
              <p className="mb-2 text-xs" style={{ color: 'var(--ev-muted)' }}>
                42 attacks across 5 categories + 15 benign prompts, run against the real guardrail stack.
              </p>
              {redteam && (
                <div className="flex flex-col gap-2">
                  <div className="flex gap-4 text-xs">
                    <span style={{ color: redteam.block_rate >= 0.95 ? 'var(--ev-high)' : '#f87171' }}>
                      Block rate: {pct(redteam.block_rate)}
                    </span>
                    <span style={{ color: redteam.false_positive_rate <= 0.1 ? 'var(--ev-high)' : '#f87171' }}>
                      False positives: {pct(redteam.false_positive_rate)}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(redteam.by_category).map(([cat, stats]) => (
                      <Badge key={cat} variant="outline">
                        {cat}: {stats.blocked}/{stats.total}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </section>

            <section
              ref={(el) => { sectionRefs.current.datasets = el }}
              id="datasets"
              className="rounded-2xl border p-4"
              style={{ borderColor: 'var(--ev-border)', background: 'linear-gradient(180deg, var(--ev-bg-from), var(--ev-bg-to))' }}
            >
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold" style={{ color: 'var(--ev-text)' }}>
                  Synthetic Eval Dataset
                </h2>
                <Button size="sm" onClick={() => void handleGenerate()} disabled={generating}>
                  {generating ? <Loader2 className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
                  Generate dataset
                </Button>
              </div>
              {dataset ? (
                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="outline">v{dataset.version}</Badge>
                  <Badge variant="outline">{dataset.item_count} items</Badge>
                  {Object.entries(dataset.categories).map(([cat, count]) => (
                    <Badge key={cat} variant="secondary">
                      {cat}: {count}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-xs" style={{ color: 'var(--ev-muted)' }}>No dataset generated yet for this document.</p>
              )}
            </section>

            <section
              ref={(el) => { sectionRefs.current.benchmarks = el }}
              id="benchmarks"
              className="rounded-2xl border p-4"
              style={{ borderColor: 'var(--ev-border)', background: 'linear-gradient(180deg, var(--ev-bg-from), var(--ev-bg-to))' }}
            >
              <h2 className="mb-2 text-sm font-semibold" style={{ color: 'var(--ev-text)' }}>
                Benchmark runs
              </h2>
              {!runsLoaded && <p className="text-xs" style={{ color: 'var(--ev-muted)' }}>Loading...</p>}
              {runsLoaded && runs.length === 0 && (
                <p className="text-xs" style={{ color: 'var(--ev-muted)' }}>
                  No benchmark runs yet — click "Run benchmark" above.
                </p>
              )}
              {latest && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr style={{ color: 'var(--ev-muted)' }}>
                        <th className="py-2 pr-3">Config</th>
                        <th className="py-2 pr-3">nDCG@5</th>
                        <th className="py-2 pr-3">Faithful</th>
                        <th className="py-2 pr-3">p95 (ms)</th>
                        <th className="py-2 pr-3">Score</th>
                        <th className="py-2">Gate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {latest.config_results.map((r) => (
                        <tr key={r.name} className="border-t" style={{ borderColor: 'var(--ev-border)' }}>
                          <td className="py-2 pr-3 font-medium" style={{ color: 'var(--ev-text)' }}>
                            {r.name}
                            {r.name === latest.recommended_config && (
                              <Badge variant="glow" className="ml-1.5">recommended</Badge>
                            )}
                          </td>
                          <td className="py-2 pr-3 tabular-nums" style={{ color: 'var(--ev-text)' }}>
                            {(r.retrieval_metrics.ndcg_at_5 ?? 0).toFixed(3)}
                          </td>
                          <td className="py-2 pr-3 tabular-nums" style={{ color: 'var(--ev-text)' }}>{r.faithfulness.toFixed(3)}</td>
                          <td className="py-2 pr-3 tabular-nums" style={{ color: 'var(--ev-text)' }}>{Math.round(r.p95_latency_ms)}</td>
                          <td className="py-2 pr-3 tabular-nums" style={{ color: 'var(--ev-text)' }}>{r.production_score.toFixed(3)}</td>
                          <td className="py-2">
                            <Badge variant={r.passes_hard_gates ? 'success' : 'destructive'}>
                              {r.passes_hard_gates ? 'pass' : 'fail'}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          <div className="flex flex-col gap-4">
            <div
              ref={(el) => { sectionRefs.current['knowledge-graph'] = el }}
              id="knowledge-graph"
              className="h-72 overflow-hidden rounded-2xl border lg:h-96"
              style={{ borderColor: 'rgba(140,130,255,0.5)' }}
            >
              {graphNodes.length > 0 ? (
                <Suspense fallback={<div className="flex h-full items-center justify-center text-xs" style={{ color: 'var(--ev-muted)' }}>Loading graph...</div>}>
                  <KnowledgeGraphCanvas
                    nodes={graphNodes}
                    edges={graphEdges}
                    onSelectEntity={() => {}}
                  />
                </Suspense>
              ) : (
                <div className="flex h-full flex-col items-center justify-center gap-1 bg-black text-center" style={{ color: 'var(--ev-muted)' }}>
                  <p className="text-sm">Knowledge Graph</p>
                  <p className="text-xs">No entities extracted yet for this document.</p>
                </div>
              )}
            </div>
            <div
              className="rounded-2xl border p-4"
              style={{ borderColor: 'var(--ev-border)', background: 'linear-gradient(180deg, var(--ev-bg-from), var(--ev-bg-to))' }}
            >
              <RunHealthPanel runs={runs} />
            </div>
          </div>
        </div>
        {/* Keep the rail's full section list referenced so EV-2's anchors always resolve. */}
        <span className="sr-only">{EVAL_SECTIONS.map((s) => s.label).join(', ')}</span>
      </div>
    </div>
  )
}
