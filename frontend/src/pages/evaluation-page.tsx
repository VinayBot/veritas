import { useState } from 'react'
import { toast } from 'sonner'
import { FlaskConical, Loader2, ShieldAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { StateMessage } from '@/components/ui/state-message'
import { useAppStore } from '@/store/app-store'
import { generateDataset, runBenchmark, runRedteam, ApiError } from '@/lib/api/client'
import type {
  BenchmarkRunResponse,
  GenerateDatasetResponse,
  RedTeamRunResponse,
} from '@/lib/api/types'

export function EvaluationPage() {
  const { documentId } = useAppStore()
  const [generating, setGenerating] = useState(false)
  const [dataset, setDataset] = useState<GenerateDatasetResponse | null>(null)
  const [benchmarking, setBenchmarking] = useState(false)
  const [benchmark, setBenchmark] = useState<BenchmarkRunResponse | null>(null)
  const [redteamRunning, setRedteamRunning] = useState(false)
  const [redteam, setRedteam] = useState<RedTeamRunResponse | null>(null)

  async function handleRedteam() {
    setRedteamRunning(true)
    try {
      const data = await runRedteam()
      setRedteam(data)
      toast.success(`Red-team: ${(data.block_rate * 100).toFixed(1)}% blocked`)
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
      setBenchmark(data)
      toast.success(`Benchmark complete — recommended: ${data.recommended_config ?? 'none'}`)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Benchmark run failed')
    } finally {
      setBenchmarking(false)
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
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <header>
        <h1 className="font-display text-2xl font-semibold text-foreground">Evaluation</h1>
        <p className="text-sm text-muted-foreground">
          A real synthetic eval set, scored against real retrieval/agent configs — the same
          engine behind <code className="text-xs">make eval</code>. This can take several
          minutes; every number below comes from an actual run.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Synthetic Eval Dataset</CardTitle>
          <CardDescription>
            Generated from this document's own chunks — factoid, multi-hop, comparison,
            unanswerable, and PII categories.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => void handleGenerate()} disabled={generating}>
            {generating ? <Loader2 className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
            {generating ? 'Generating...' : 'Generate dataset'}
          </Button>
          {dataset && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              <Badge variant="outline">v{dataset.version}</Badge>
              <Badge variant="outline">{dataset.item_count} items</Badge>
              {Object.entries(dataset.categories).map(([cat, count]) => (
                <Badge key={cat} variant="secondary">
                  {cat}: {count}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Benchmark Run</CardTitle>
          <CardDescription>
            Scores bm25, dense, hybrid, hybrid_rerank_hyde, graph, and agentic against a fresh
            eval set, plus the real red-team suite for the safety signal.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => void handleBenchmark()} disabled={benchmarking}>
            {benchmarking ? <Loader2 className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
            {benchmarking ? 'Running (this takes a while)...' : 'Run benchmark'}
          </Button>

          {benchmark && (
            <div className="mt-4 flex flex-col gap-3">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-border text-muted-foreground">
                      <th className="py-2 pr-3">Config</th>
                      <th className="py-2 pr-3">nDCG@5</th>
                      <th className="py-2 pr-3">Faithful</th>
                      <th className="py-2 pr-3">Correct</th>
                      <th className="py-2 pr-3">p95 (ms)</th>
                      <th className="py-2 pr-3">Score</th>
                      <th className="py-2">Gate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {benchmark.config_results.map((r) => (
                      <tr
                        key={r.name}
                        className={`border-b border-border/50 ${
                          r.name === benchmark.recommended_config ? 'bg-accent/5' : ''
                        }`}
                      >
                        <td className="py-2 pr-3 font-medium text-foreground">
                          {r.name}
                          {r.name === benchmark.recommended_config && (
                            <Badge variant="glow" className="ml-1.5">
                              recommended
                            </Badge>
                          )}
                        </td>
                        <td className="py-2 pr-3 tabular-nums">
                          {(r.retrieval_metrics.ndcg_at_5 ?? 0).toFixed(3)}
                        </td>
                        <td className="py-2 pr-3 tabular-nums">{r.faithfulness.toFixed(3)}</td>
                        <td className="py-2 pr-3 tabular-nums">{r.correctness.toFixed(3)}</td>
                        <td className="py-2 pr-3 tabular-nums">{Math.round(r.p95_latency_ms)}</td>
                        <td className="py-2 pr-3 tabular-nums">{r.production_score.toFixed(3)}</td>
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
              <p className="text-xs text-muted-foreground">
                Safety: injection block rate {(benchmark.injection_block_rate * 100).toFixed(1)}%,
                PII leak count {benchmark.pii_leak_count}.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card data-testid="safety-redteam-card">
        <CardHeader>
          <CardTitle>Safety / Red-Team Suite</CardTitle>
          <CardDescription>
            42 attacks across 5 categories + 15 benign prompts, run against the real guardrail
            stack right now — the same safety signal the Benchmark Run above also reports, but
            immediate and standalone rather than bundled into a full eval pass.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => void handleRedteam()} disabled={redteamRunning}>
            {redteamRunning ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ShieldAlert className="size-4" />
            )}
            {redteamRunning ? 'Running attack suite...' : 'Run red-team suite'}
          </Button>
          {redteam && (
            <div className="mt-4 flex flex-col gap-3">
              <div className="flex gap-4">
                <SafetyMetric
                  label="Block rate"
                  value={`${(redteam.block_rate * 100).toFixed(1)}%`}
                  good={redteam.block_rate >= 0.95}
                />
                <SafetyMetric
                  label="False positives"
                  value={`${(redteam.false_positive_rate * 100).toFixed(1)}%`}
                  good={redteam.false_positive_rate <= 0.1}
                />
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
        </CardContent>
      </Card>
    </div>
  )
}

function SafetyMetric({ label, value, good }: { label: string; value: string; good: boolean }) {
  return (
    <div className="rounded-md border border-border bg-surface-raised px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`font-display text-lg font-semibold ${good ? 'text-success' : 'text-danger'}`}>
        {value}
      </p>
    </div>
  )
}
