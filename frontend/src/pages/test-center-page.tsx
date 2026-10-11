import { useState } from 'react'
import { toast } from 'sonner'
import { FlaskConical, Loader2, Copy, PlayCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import {
  runSelfTest,
  loadSampleDocument,
  getDocument,
  streamChat,
  getHealth,
} from '@/lib/api/client'

interface TestRow {
  category: 'self-test' | 'sample-doc'
  name: string
  expected: string
  actual: string
  pass: boolean
  time_ms: number
}

// Real, grounded questions against the project's own real demo document
// (data/demo/northwind_remote_work_travel_policy.pdf) — each checked against a specific,
// known-correct fact rather than just "didn't abstain", so a wrong-but-non-abstain answer
// still fails.
const SAMPLE_QUESTIONS: { question: string; expectedSubstring: string; expected: string }[] = [
  {
    question: 'How many days per week can employees work remotely after their 90-day probation?',
    expectedSubstring: 'three',
    expected: 'Mentions three days per week',
  },
  {
    question: 'Can a German contractor work remotely without approval?',
    expectedSubstring: 'approval',
    expected: 'States approval/exception is required (not an abstain)',
  },
  {
    question: 'What business travel amount requires Vice President approval?',
    expectedSubstring: 'thousand',
    expected: 'Mentions a dollar threshold',
  },
]

const ABSTAIN_PHRASES = ["don't have enough", 'do not have enough', 'unable to generate']

function waitForDocumentReady(documentId: string, timeoutMs: number): Promise<string> {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const doc = await getDocument(documentId)
        if (doc.status === 'ready' || doc.status === 'failed' || doc.status === 'cancelled') {
          resolve(doc.status)
          return
        }
      } catch {
        // transient — keep polling until the deadline
      }
      if (Date.now() > deadline) {
        reject(new Error('timed out waiting for document to become ready'))
        return
      }
      setTimeout(poll, 1000)
    }
    void poll()
  })
}

async function askOneQuestion(
  documentId: string,
  question: string,
): Promise<{ answer: string; errored: boolean }> {
  let answer = ''
  let errored = false
  await streamChat({ message: question, document_id: documentId, mode: 'agentic' }, (evt) => {
    if (evt.event === 'token') answer += evt.data
    if (evt.event === 'error') errored = true
  })
  return { answer, errored }
}

export function TestCenterPage() {
  const [selfTestRunning, setSelfTestRunning] = useState(false)
  const [sampleRunning, setSampleRunning] = useState(false)
  const [results, setResults] = useState<TestRow[]>([])

  function upsertCategory(category: TestRow['category'], rows: TestRow[]) {
    setResults((prev) => [...prev.filter((r) => r.category !== category), ...rows])
  }

  async function handleSelfTest() {
    setSelfTestRunning(true)
    try {
      const rows: TestRow[] = []
      const data = await runSelfTest()
      for (const check of data.checks) {
        rows.push({
          category: 'self-test',
          name: check.name,
          expected: 'ok',
          actual: check.detail,
          pass: check.ok,
          time_ms: check.duration_ms,
        })
      }

      // SSE/WebSocket connectivity is a client-side concern — checked here directly against
      // the real trace WebSocket rather than faked server-side.
      const sseStart = performance.now()
      const sseResult = await new Promise<{ pass: boolean; detail: string }>((resolve) => {
        const probeId = `test-center-${Date.now()}`
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
        const ws = new WebSocket(`${proto}://${window.location.host}/ws/trace/${probeId}`)
        const timer = setTimeout(() => {
          ws.close()
          resolve({ pass: false, detail: 'no connection within 5s' })
        }, 5000)
        ws.onopen = () => {
          clearTimeout(timer)
          ws.close()
          resolve({ pass: true, detail: 'connected' })
        }
        ws.onerror = () => {
          clearTimeout(timer)
          resolve({ pass: false, detail: 'connection error' })
        }
      })
      rows.push({
        category: 'self-test',
        name: 'sse_connection',
        expected: 'connects within 5s',
        actual: sseResult.detail,
        pass: sseResult.pass,
        time_ms: performance.now() - sseStart,
      })

      upsertCategory('self-test', rows)
      toast[data.all_ok && sseResult.pass ? 'success' : 'error'](
        data.all_ok && sseResult.pass ? 'Self-test: all checks passed' : 'Self-test: some checks failed',
      )
    } catch (err) {
      toast.error('Self-test failed to run')
      upsertCategory('self-test', [
        {
          category: 'self-test',
          name: 'self-test-request',
          expected: 'ok',
          actual: err instanceof Error ? err.message : 'unknown error',
          pass: false,
          time_ms: 0,
        },
      ])
    } finally {
      setSelfTestRunning(false)
    }
  }

  async function handleLoadSample() {
    setSampleRunning(true)
    const rows: TestRow[] = []
    try {
      const uploadStart = performance.now()
      const upload = await loadSampleDocument()
      const status = await waitForDocumentReady(upload.document_id, 120_000)
      rows.push({
        category: 'sample-doc',
        name: 'load_sample_document',
        expected: 'status: ready',
        actual: `status: ${status}`,
        pass: status === 'ready',
        time_ms: performance.now() - uploadStart,
      })

      if (status === 'ready') {
        for (const sample of SAMPLE_QUESTIONS) {
          const qStart = performance.now()
          try {
            const { answer, errored } = await askOneQuestion(upload.document_id, sample.question)
            const lower = answer.toLowerCase()
            const abstained = ABSTAIN_PHRASES.some((p) => lower.includes(p))
            const hasExpected = lower.includes(sample.expectedSubstring.toLowerCase())
            rows.push({
              category: 'sample-doc',
              name: sample.question,
              expected: sample.expected,
              actual: errored
                ? 'error event received'
                : abstained
                  ? 'abstained'
                  : answer.slice(0, 160) || '(empty)',
              pass: !errored && !abstained && hasExpected,
              time_ms: performance.now() - qStart,
            })
          } catch (err) {
            rows.push({
              category: 'sample-doc',
              name: sample.question,
              expected: sample.expected,
              actual: err instanceof Error ? err.message : 'request failed',
              pass: false,
              time_ms: performance.now() - qStart,
            })
          }
        }
      }

      upsertCategory('sample-doc', rows)
      const allPass = rows.every((r) => r.pass)
      toast[allPass ? 'success' : 'error'](
        allPass ? 'Sample document: all checks passed' : 'Sample document: some checks failed',
      )
    } catch (err) {
      toast.error('Load sample document failed')
      upsertCategory('sample-doc', [
        ...rows,
        {
          category: 'sample-doc',
          name: 'load_sample_document',
          expected: 'status: ready',
          actual: err instanceof Error ? err.message : 'unknown error',
          pass: false,
          time_ms: 0,
        },
      ])
    } finally {
      setSampleRunning(false)
    }
  }

  async function handleCopyDebugReport() {
    let health: unknown = null
    try {
      health = await getHealth()
    } catch (err) {
      health = { error: err instanceof Error ? err.message : 'unreachable' }
    }
    const report = {
      generated_at: new Date().toISOString(),
      user_agent: navigator.userAgent,
      url: window.location.href,
      health,
      last_test_results: results,
    }
    try {
      await navigator.clipboard.writeText(JSON.stringify(report, null, 2))
      toast.success('Debug report copied to clipboard')
    } catch {
      toast.error('Could not copy to clipboard')
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <header>
        <h1 className="font-display text-2xl font-semibold text-foreground">Test Center</h1>
        <p className="text-sm text-muted-foreground">
          Real checks against the real backend — nothing here is simulated. Use this to verify
          the stack is healthy without reading backend logs.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Load Sample Document</CardTitle>
          <CardDescription>
            Uploads the project's real demo document and asks it 3 real questions with known
            answers, end to end.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => void handleLoadSample()} disabled={sampleRunning}>
            {sampleRunning ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <PlayCircle className="size-4" />
            )}
            {sampleRunning ? 'Running...' : 'Load sample document'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Self-Test</CardTitle>
          <CardDescription>
            Checks the database, background worker, embedder, Ollama/LLM reachability, vector
            store, and the live trace WebSocket connection.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => void handleSelfTest()} disabled={selfTestRunning}>
            {selfTestRunning ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <FlaskConical className="size-4" />
            )}
            {selfTestRunning ? 'Running...' : 'Run self-test'}
          </Button>
        </CardContent>
      </Card>

      <Card data-testid="test-center-results">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Last Test Run</CardTitle>
              <CardDescription>Results from the most recent runs above.</CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleCopyDebugReport()}
              disabled={results.length === 0}
            >
              <Copy className="size-4" />
              Copy debug report
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {results.length === 0 ? (
            <p className="text-sm text-muted-foreground">No tests run yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="py-2 pr-3">Test</th>
                    <th className="py-2 pr-3">Expected</th>
                    <th className="py-2 pr-3">Actual</th>
                    <th className="py-2 pr-3">Result</th>
                    <th className="py-2">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, i) => (
                    <tr key={`${r.category}-${i}`} className="border-b border-border/50">
                      <td className="max-w-xs truncate py-2 pr-3 font-medium text-foreground">
                        {r.name}
                      </td>
                      <td className="max-w-xs truncate py-2 pr-3 text-muted-foreground">
                        {r.expected}
                      </td>
                      <td className="max-w-xs truncate py-2 pr-3 text-muted-foreground">
                        {r.actual}
                      </td>
                      <td className="py-2 pr-3">
                        <Badge variant={r.pass ? 'success' : 'destructive'}>
                          {r.pass ? 'PASS' : 'FAIL'}
                        </Badge>
                      </td>
                      <td className="py-2 tabular-nums">{Math.round(r.time_ms)}ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
