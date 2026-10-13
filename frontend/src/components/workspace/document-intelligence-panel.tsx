import { useCallback, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'
import { Check, X, Sparkles, ScanSearch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Gauge } from '@/components/ui/gauge'
import { StateMessage, type ComponentStatus } from '@/components/ui/state-message'
import { RingHero, type RingDataset } from '@/components/workspace/ring-hero'
import { PipelineFacts } from '@/components/workspace/pipeline-facts'
import { RobotCharacter, type RobotState } from '@/components/robot/robot-character'
import {
  getAdvisor,
  runAdvisor,
  decideAdvisor,
  getReport,
  getProfile,
  ApiError,
} from '@/lib/api/client'
import type {
  AdvisorResponse,
  CandidateResultOut,
  DocumentResponse,
  ProfileResponse,
  ReportResponse,
} from '@/lib/api/types'

const PII_COLORS = ['#8b5cf6', '#34d399', '#fbbf24', '#f87171', '#60a5fa', '#f472b6', '#2dd4bf', '#fb923c']

/** Fix 1's Workspace Document Intelligence panel — replaces the Dashboard tab (see
 * docs/DECISIONS.md: TASK 4 removes it once this exists). Ring hero, pipeline fact chips, the
 * analyst robot, the advisor arena (accept/ignore), and the per-answer report all live here,
 * in the Workspace's right half, springing in as soon as a document exists. */
export function DocumentIntelligencePanel({
  doc,
  mode,
  lastReportId,
  stillIngesting,
}: {
  doc: DocumentResponse
  mode: string
  lastReportId: string | null
  stillIngesting: boolean
}) {
  const [profile, setProfile] = useState<ProfileResponse | null>(null)
  const [advisor, setAdvisor] = useState<AdvisorResponse | null>(null)
  const [advisorStatus, setAdvisorStatus] = useState<ComponentStatus>('loading')
  const [running, setRunning] = useState(false)
  const [deciding, setDeciding] = useState<'accept' | 'ignore' | null>(null)
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [reportStatus, setReportStatus] = useState<ComponentStatus>('loading')

  const loadAdvisor = useCallback(async () => {
    try {
      const data = await getAdvisor(doc.id)
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
  }, [doc.id])

  useEffect(() => {
    void loadAdvisor()
  }, [loadAdvisor, doc.enrichment_status])

  useEffect(() => {
    if (doc.status !== 'ready') return
    getProfile(doc.id)
      .then(setProfile)
      .catch(() => {})
  }, [doc.id, doc.status])

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
    setRunning(true)
    try {
      const data = await runAdvisor(doc.id)
      setAdvisor(data)
      setAdvisorStatus('success')
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Advisor run failed')
    } finally {
      setRunning(false)
    }
  }

  async function handleDecision(decision: 'accept' | 'ignore') {
    setDeciding(decision)
    try {
      const data = await decideAdvisor(doc.id, decision)
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

  const ringDatasets: RingDataset[] = []
  const piiEntries = Object.entries(doc.pii_counts)
  if (piiEntries.length > 0) {
    ringDatasets.push({
      key: 'pii',
      label: 'PII by type',
      centerLabel: 'PII items',
      centerValue: piiEntries.reduce((a, [, v]) => a + v, 0),
      segments: piiEntries.map(([label, value], i) => ({
        label,
        value,
        color: PII_COLORS[i % PII_COLORS.length],
      })),
    })
  }
  if (profile) {
    const prose = Math.max(0, 1 - profile.table_ratio - profile.list_ratio - profile.code_ratio)
    ringDatasets.push({
      key: 'content-type',
      label: 'Content type',
      centerLabel: 'Tokens',
      centerValue: profile.tokens,
      segments: [
        { label: 'Prose', value: prose, color: '#8b5cf6' },
        { label: 'Tables', value: profile.table_ratio, color: '#34d399' },
        { label: 'Lists', value: profile.list_ratio, color: '#fbbf24' },
        { label: 'Code', value: profile.code_ratio, color: '#60a5fa' },
      ].filter((s) => s.value > 0.001),
    })
  }
  if (ringDatasets.length === 0) {
    ringDatasets.push({
      key: 'chunks',
      label: 'Chunks',
      centerLabel: 'Chunks indexed',
      centerValue: doc.chunk_count ?? 0,
      segments: [{ label: doc.chunk_strategy ?? 'indexed', value: doc.chunk_count ?? 1, color: '#8b5cf6' }],
    })
  }

  const analystState: RobotState = stillIngesting
    ? 'working'
    : advisorStatus === 'loading' || running
      ? 'working'
      : advisorStatus === 'success' && advisor
        ? 'idle'
        : 'idle'

  return (
    <motion.aside
      initial={{ opacity: 0, x: 24 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="flex h-full w-full flex-col gap-5 overflow-y-auto rounded-lg border border-border bg-surface p-5 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      data-testid="document-intelligence-panel"
      data-lenis-prevent
      tabIndex={0}
      role="region"
      aria-label="Document intelligence panel"
    >
      <RingHero datasets={ringDatasets} />
      <PipelineFacts doc={doc} mode={mode} />

      <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface-raised p-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
            <ScanSearch className="size-4 text-accent" /> Analyst
          </h3>
          {!stillIngesting && (
            <Button size="sm" variant="outline" onClick={() => void handleRunAdvisor()} disabled={running}>
              <Sparkles className="size-3.5" /> {running ? 'Running...' : 'Re-run'}
            </Button>
          )}
        </div>

        <div className="flex items-center justify-center py-2">
          <RobotCharacter state={analystState} scale={0.9} action="advisor" />
        </div>

        {stillIngesting ? (
          <StateMessage
            status="empty"
            title="Still ingesting"
            description={`Still "${doc.current_stage ?? doc.status}" — the analyst will scan once ready.`}
          />
        ) : (
          <>
            {advisorStatus === 'loading' && <StateMessage status="empty" title="Scanning the document..." />}
            {advisorStatus === 'error' && <StateMessage status="error" />}
            {advisorStatus === 'empty' && (
              <div className="flex flex-col items-center gap-3 py-2 text-center">
                <StateMessage
                  status="empty"
                  title="No recommendation yet"
                  description="Either the advisor hasn't run, or there are too few chunks for a meaningful comparison."
                />
                <Button size="sm" onClick={() => void handleRunAdvisor()} disabled={running}>
                  {running ? 'Running tournament...' : 'Run advisor now'}
                </Button>
              </div>
            )}
            {advisorStatus === 'success' && advisor && (
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <CandidateCard title="Current" candidate={advisor.baseline} />
                  <CandidateCard title="Recommended" candidate={advisor.suggested} highlight />
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium text-foreground">
                    {advisor.gain_ndcg_points >= 0 ? '+' : ''}
                    {advisor.gain_ndcg_points.toFixed(2)} nDCG@5 points
                  </span>
                  <span className="text-muted-foreground">vs current</span>
                </div>
                <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
                  {advisor.rationale.map((r, i) => (
                    <li key={i}>— {r}</li>
                  ))}
                </ul>
                <div className="rounded-md border border-border bg-surface p-2.5 text-xs">
                  <span className="font-medium text-foreground">Suggested RAG mode: {advisor.suggested_mode}</span>
                  <p className="mt-1 text-muted-foreground">{advisor.mode_reason}</p>
                </div>
                <div className="flex items-center gap-2">
                  {advisor.decision ? (
                    <Badge variant={advisor.decision === 'accept' ? 'success' : 'outline'}>
                      decision: {advisor.decision}
                    </Badge>
                  ) : (
                    <>
                      <Button size="sm" onClick={() => void handleDecision('accept')} disabled={deciding !== null}>
                        <Check className="size-3.5" /> {deciding === 'accept' ? 'Re-indexing...' : 'Accept'}
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
      </section>

      <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface-raised p-4">
        <h3 className="text-sm font-semibold text-foreground">Latest Answer Quality</h3>
        <AnimatePresence mode="wait">
          {reportStatus === 'empty' && (
            <StateMessage status="empty" description="Chat with this document to see a quality report." />
          )}
          {reportStatus === 'loading' && <StateMessage status="empty" title="Loading..." />}
          {reportStatus === 'error' && <StateMessage status="error" />}
          {reportStatus === 'success' && report && (
            <motion.div
              key={report.id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex flex-col gap-3"
            >
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Q:</span> {report.query}
              </p>
              <div className="flex flex-wrap justify-around gap-3">
                <Gauge
                  value={Math.round((report.quality.faithfulness ?? 0) * 100)}
                  label="Faithfulness"
                  status={report.quality.faithfulness === null ? 'empty' : 'success'}
                  size={80}
                />
                <Gauge value={Math.round(report.quality.relevancy * 100)} label="Relevancy" size={80} />
                <Gauge
                  value={Math.round(report.quality.citation_validity * 100)}
                  label="Citations"
                  size={80}
                />
                <Gauge value={Math.round(report.quality.confidence * 100)} label="Confidence" size={80} />
              </div>
              {report.routing && (
                <p className="text-xs text-muted-foreground">
                  Answered by{' '}
                  <span className="text-foreground">{report.routing.model_used.replace('ollama/', '')}</span> in{' '}
                  {Math.round(report.routing.latency_ms)}ms
                  {report.routing.fell_back && ` (fell back from ${report.routing.primary_model.replace('ollama/', '')})`}.
                </p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </section>
    </motion.aside>
  )
}

function CandidateCard({ title, candidate, highlight }: { title: string; candidate: CandidateResultOut; highlight?: boolean }) {
  return (
    <div className={`rounded-md border p-2.5 text-xs ${highlight ? 'border-accent/40 bg-accent/5' : 'border-border bg-surface'}`}>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="font-medium text-foreground">{title}</span>
        <Badge variant="outline">{candidate.name}</Badge>
      </div>
      <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-muted-foreground">
        <dt>Strategy</dt>
        <dd className="text-right text-foreground">
          {candidate.chunking_strategy} ({String(candidate.chunking_kwargs.size ?? '?')})
        </dd>
        <dt>nDCG@5</dt>
        <dd className="text-right text-foreground">{(candidate.retrieval_metrics.ndcg_at_5 ?? 0).toFixed(3)}</dd>
        <dt>Faithfulness</dt>
        <dd className="text-right text-foreground">{candidate.faithfulness.toFixed(2)}</dd>
        <dt>Latency</dt>
        <dd className="text-right text-foreground">{Math.round(candidate.avg_latency_ms)}ms</dd>
      </dl>
    </div>
  )
}
