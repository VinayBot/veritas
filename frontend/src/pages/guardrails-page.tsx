import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { ShieldAlert, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { StateMessage, type ComponentStatus } from '@/components/ui/state-message'
import { getAudit, runRedteam } from '@/lib/api/client'
import type { AuditEntry, RedTeamRunResponse } from '@/lib/api/types'

const DECISION_VARIANT: Record<string, 'success' | 'destructive' | 'outline' | 'warning'> = {
  allow: 'success',
  block: 'destructive',
  redact: 'warning',
  escalate: 'warning',
}

export function GuardrailsPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [auditStatus, setAuditStatus] = useState<ComponentStatus>('loading')
  const [running, setRunning] = useState(false)
  const [redteam, setRedteam] = useState<RedTeamRunResponse | null>(null)

  const loadAudit = useCallback(async () => {
    setAuditStatus('loading')
    try {
      const data = await getAudit({ limit: 50 })
      setEntries(data.entries)
      setAuditStatus(data.entries.length === 0 ? 'empty' : 'success')
    } catch {
      setAuditStatus('error')
    }
  }, [])

  useEffect(() => {
    void loadAudit()
  }, [loadAudit])

  async function handleRedteam() {
    setRunning(true)
    try {
      const data = await runRedteam()
      setRedteam(data)
      toast.success(`Red-team: ${(data.block_rate * 100).toFixed(1)}% blocked`)
      void loadAudit()
    } catch {
      toast.error('Red-team run failed')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <header>
        <h1 className="font-display text-2xl font-semibold text-foreground">Guardrails</h1>
        <p className="text-sm text-muted-foreground">
          Every guardrail decision — allow or block — is logged here, and the red-team suite
          runs the real attack corpus against the live input guardrail.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Red-Team Suite</CardTitle>
          <CardDescription>
            42 attacks across 5 categories + 15 benign prompts, run against the real guardrail
            stack right now.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => void handleRedteam()} disabled={running}>
            {running ? <Loader2 className="size-4 animate-spin" /> : <ShieldAlert className="size-4" />}
            {running ? 'Running attack suite...' : 'Run red-team suite'}
          </Button>
          {redteam && (
            <div className="mt-4 flex flex-col gap-3">
              <div className="flex gap-4">
                <Metric
                  label="Block rate"
                  value={`${(redteam.block_rate * 100).toFixed(1)}%`}
                  good={redteam.block_rate >= 0.95}
                />
                <Metric
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

      <Card>
        <CardHeader>
          <CardTitle>Audit Log</CardTitle>
          <CardDescription>Most recent guardrail decisions, every layer.</CardDescription>
        </CardHeader>
        <CardContent>
          {auditStatus === 'loading' && <StateMessage status="empty" title="Loading..." />}
          {auditStatus === 'error' && <StateMessage status="error" />}
          {auditStatus === 'empty' && (
            <StateMessage status="empty" description="No guardrail decisions logged yet." />
          )}
          {auditStatus === 'success' && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="py-2 pr-3">Time</th>
                    <th className="py-2 pr-3">Layer</th>
                    <th className="py-2 pr-3">Rule</th>
                    <th className="py-2 pr-3">Score</th>
                    <th className="py-2 pr-3">Decision</th>
                    <th className="py-2">Excerpt</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e) => (
                    <tr key={e.id} className="border-b border-border/50">
                      <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                        {new Date(e.created_at).toLocaleTimeString()}
                      </td>
                      <td className="py-2 pr-3">{e.layer}</td>
                      <td className="py-2 pr-3">{e.rule}</td>
                      <td className="py-2 pr-3 tabular-nums">{e.score?.toFixed(2) ?? '—'}</td>
                      <td className="py-2 pr-3">
                        <Badge variant={DECISION_VARIANT[e.decision] ?? 'outline'}>
                          {e.decision}
                        </Badge>
                      </td>
                      <td className="max-w-xs truncate py-2 text-muted-foreground">
                        {e.redacted_excerpt ?? '—'}
                      </td>
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

function Metric({ label, value, good }: { label: string; value: string; good: boolean }) {
  return (
    <div className="rounded-md border border-border bg-surface-raised px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`font-display text-lg font-semibold ${good ? 'text-success' : 'text-danger'}`}>
        {value}
      </p>
    </div>
  )
}
