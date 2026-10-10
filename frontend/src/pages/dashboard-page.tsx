import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, X, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Gauge } from '@/components/ui/gauge'
import { StateMessage, type ComponentStatus } from '@/components/ui/state-message'
import { useAppStore } from '@/store/app-store'
import { useDocumentStatus } from '@/hooks/useDocumentStatus'
import {
  getAdvisor,
  runAdvisor,
  decideAdvisor,
  getReport,
  ApiError,
} from '@/lib/api/client'
import type { AdvisorResponse, CandidateResultOut, ReportResponse } from '@/lib/api/types'

export function DashboardPage() {
  const { documentId, lastReportId } = useAppStore()
  const { doc } = useDocumentStatus(documentId)
  const stillIngesting = doc !== null && doc.status !== 'ready' && doc.status !== 'failed'
  const [advisor, setAdvisor] = useState<AdvisorResponse | null>(null)
  const [advisorStatus, setAdvisorStatus] = useState<ComponentStatus>('loading')
  const [running, setRunning] = useState(false)
  const [deciding, setDeciding] = useState<'accept' | 'ignore' | null>(null)
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [reportStatus, setReportStatus] = useState<ComponentStatus>('loading')

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

  // Re-fetches whenever enrichment_status changes (not just on mount) — graph/profile/advisor
  // run as a background phase that can still be in flight when this page is first visited
  // (the document only needs to be "ready" for chat, not fully enriched), so the automatic
  // recommendation that was simply absent a moment ago can appear without the user having to
  // manually click "Run advisor now" once it actually finishes.
  useEffect(() => {
    void loadAdvisor()
  }, [loadAdvisor, doc?.enrichment_status])

  useEffect(() => {
    if (!lastReportId) {
      setReportStatus('empty')
      return
    }
    setReportStatus('loading')
    getReport(lastReportId)
      .then((r) => {
        setReport(r)
        setReportStatus('success')
      })
      .catch(() => setReportStatus('error'))
  }, [lastReportId])

  async function handleRunAdvisor() {
    if (!documentId) return
    setRunning(true)
    try {
      const data = await runAdvisor(documentId)
      setAdvisor(data)
      setAdvisorStatus('success')
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Advisor run failed')
    } finally {
      setRunning(false)
    }
  }

  async function handleDecision(decision: 'accept' | 'ignore') {
    if (!documentId) return
    setDeciding(decision)
    try {
      const data = await decideAdvisor(documentId, decision)
      setAdvisor(data)
      toast.success(
        decision === 'accept'
          ? 'Document re-indexed with the suggested config'
          : 'Recommendation ignored — index unchanged',
      )
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Decision failed')
    } finally {
      setDeciding(null)
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
        <h1 className="font-display text-2xl font-semibold text-foreground">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Real tournament results and the latest answer's measured quality — nothing here is a
          placeholder number.
        </p>
      </header>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <div>
              <CardTitle>Model &amp; Chunking Advisor</CardTitle>
              <CardDescription>
                A real 5-candidate tournament against a synthetic eval set generated from this
                document's own chunks.
              </CardDescription>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleRunAdvisor()}
              disabled={running || stillIngesting}
            >
              <Sparkles className="size-3.5" /> {running ? 'Running...' : 'Re-run'}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {stillIngesting ? (
            <StateMessage
              status="empty"
              title="Still ingesting"
              description={`This document is still "${doc?.current_stage ?? doc?.status}" in Workspace — come back once it reaches ready.`}
            />
          ) : (
            <>
              {advisorStatus === 'loading' && (
                <StateMessage status="empty" title="Loading..." />
              )}
              {advisorStatus === 'error' && <StateMessage status="error" />}
              {advisorStatus === 'empty' && (
                <div className="flex flex-col items-center gap-3 py-6 text-center">
                  <StateMessage
                    status="empty"
                    title="No recommendation yet"
                    description="Either the advisor hasn't run on this document, or it has too few chunks for a meaningful comparison."
                  />
                  <Button onClick={() => void handleRunAdvisor()} disabled={running}>
                    {running ? 'Running tournament...' : 'Run advisor now'}
                  </Button>
                </div>
              )}
          {advisorStatus === 'success' && advisor && (
            <div className="flex flex-col gap-5">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <CandidateCard title="Baseline" candidate={advisor.baseline} />
                <CandidateCard title="Suggested" candidate={advisor.suggested} highlight />
              </div>

              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium text-foreground">
                  {advisor.gain_ndcg_points >= 0 ? '+' : ''}
                  {advisor.gain_ndcg_points.toFixed(2)} nDCG@5 points
                </span>
                <span className="text-muted-foreground">vs baseline</span>
              </div>

              <ul className="flex flex-col gap-1.5 text-sm text-muted-foreground">
                {advisor.rationale.map((r, i) => (
                  <li key={i}>— {r}</li>
                ))}
              </ul>

              <div className="rounded-md border border-border bg-surface-raised p-3 text-sm">
                <span className="font-medium text-foreground">
                  Suggested RAG mode: {advisor.suggested_mode}
                </span>
                <p className="mt-1 text-xs text-muted-foreground">{advisor.mode_reason}</p>
              </div>

              <div className="flex items-center gap-2">
                {advisor.decision ? (
                  <Badge variant={advisor.decision === 'accept' ? 'success' : 'outline'}>
                    decision: {advisor.decision}
                  </Badge>
                ) : (
                  <>
                    <Button
                      size="sm"
                      onClick={() => void handleDecision('accept')}
                      disabled={deciding !== null}
                    >
                      <Check className="size-3.5" />{' '}
                      {deciding === 'accept' ? 'Re-indexing...' : 'Accept'}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void handleDecision('ignore')}
                      disabled={deciding !== null}
                    >
                      <X className="size-3.5" /> Ignore
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Latest Answer Quality</CardTitle>
          <CardDescription>
            Reference-free "Estimated" scores from the LLM judge, for the most recent chat turn.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {reportStatus === 'empty' && (
            <StateMessage status="empty" description="Chat with a document in Workspace first." />
          )}
          {reportStatus === 'loading' && <StateMessage status="empty" title="Loading..." />}
          {reportStatus === 'error' && <StateMessage status="error" />}
          {reportStatus === 'success' && report && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Q:</span> {report.query}
              </p>
              <div className="flex flex-wrap justify-around gap-4">
                <Gauge
                  value={Math.round((report.quality.faithfulness ?? 0) * 100)}
                  label="Faithfulness"
                  status={report.quality.faithfulness === null ? 'empty' : 'success'}
                  size={100}
                />
                <Gauge
                  value={Math.round(report.quality.relevancy * 100)}
                  label="Relevancy"
                  size={100}
                />
                <Gauge
                  value={Math.round(report.quality.citation_validity * 100)}
                  label="Citation validity"
                  size={100}
                />
                <Gauge
                  value={Math.round(report.quality.confidence * 100)}
                  label="Confidence"
                  size={100}
                />
              </div>
              {report.routing && (
                <p className="text-xs text-muted-foreground">
                  Answered by{' '}
                  <span className="text-foreground">
                    {report.routing.model_used.replace('ollama/', '')}
                  </span>{' '}
                  in {Math.round(report.routing.latency_ms)}ms
                  {report.routing.fell_back &&
                    ` (fell back from ${report.routing.primary_model.replace('ollama/', '')})`}
                  .
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function CandidateCard({
  title,
  candidate,
  highlight,
}: {
  title: string
  candidate: CandidateResultOut
  highlight?: boolean
}) {
  return (
    <div
      className={`rounded-md border p-3 text-sm ${highlight ? 'border-accent/40 bg-accent/5' : 'border-border'}`}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium text-foreground">{title}</span>
        <Badge variant="outline">{candidate.name}</Badge>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <dt>Strategy</dt>
        <dd className="text-right text-foreground">
          {candidate.chunking_strategy} ({String(candidate.chunking_kwargs.size ?? '?')})
        </dd>
        <dt>nDCG@5</dt>
        <dd className="text-right text-foreground">
          {(candidate.retrieval_metrics.ndcg_at_5 ?? 0).toFixed(3)}
        </dd>
        <dt>Faithfulness</dt>
        <dd className="text-right text-foreground">{candidate.faithfulness.toFixed(2)}</dd>
        <dt>Avg latency</dt>
        <dd className="text-right text-foreground">{Math.round(candidate.avg_latency_ms)}ms</dd>
        <dt>Chunks</dt>
        <dd className="text-right text-foreground">{candidate.index_size}</dd>
        <dt>Composite</dt>
        <dd className="text-right text-foreground">{candidate.composite_score.toFixed(3)}</dd>
      </dl>
    </div>
  )
}
