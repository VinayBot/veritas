import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ShieldAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Panel } from '@/components/ui/page'
import { StatCard } from '@/components/ui/stat-card'
import { DataTable, type Column } from '@/components/ui/data-table'
import { EmptyState, ErrorState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { Segmented } from '@/components/ui/segmented'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { InlineBar } from '@/components/ui/progress-bar'
import { useCommands, type CommandPaletteItem } from '@/components/ui/command-palette'
import { getAudit, getAuditSummary, runRedteam } from '@/lib/api/client'
import type { AuditEntry, AuditRuleSummary, AuditSummaryResponse, RedTeamRunResponse } from '@/lib/api/types'
import { compact, dateTime, pct, relativeTime } from '@/lib/format'

const DECISION_VARIANT: Record<string, 'success' | 'destructive' | 'outline' | 'warning'> = {
  allow: 'success',
  block: 'destructive',
  redact: 'warning',
  escalate: 'warning',
}

type LayerFilter = 'all' | 'input' | 'retrieval' | 'output'

interface CategoryRow {
  category: string
  total: number
  blocked: number
  block_rate: number
}

/** Guardrail decisions on real questions, and an attack suite to run against them. */
export function SafetySection() {
  const [summary, setSummary] = useState<AuditSummaryResponse | null>(null)
  const [summaryError, setSummaryError] = useState<unknown>(null)
  const [entries, setEntries] = useState<AuditEntry[] | null>(null)
  const [entriesError, setEntriesError] = useState<unknown>(null)
  const [layer, setLayer] = useState<LayerFilter>('all')
  const [trippedOnly, setTrippedOnly] = useState(false)
  const [redteam, setRedteam] = useState<RedTeamRunResponse | null>(null)
  const [redteamAt, setRedteamAt] = useState<number | null>(null)
  const [redteamRunning, setRedteamRunning] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const loadSummary = useCallback(() => {
    getAuditSummary()
      .then((data) => {
        setSummary(data)
        setSummaryError(null)
      })
      .catch(setSummaryError)
  }, [])

  const loadEntries = useCallback(() => {
    setEntries(null)
    getAudit({ layer: layer === 'all' ? undefined : layer, real_traffic_only: true, limit: 200 })
      .then((data) => {
        setEntries(data.entries)
        setEntriesError(null)
      })
      .catch(setEntriesError)
  }, [layer])

  useEffect(loadSummary, [loadSummary])
  useEffect(loadEntries, [loadEntries])

  async function handleRedteam() {
    setConfirmOpen(false)
    setRedteamRunning(true)
    try {
      const data = await runRedteam()
      setRedteam(data)
      setRedteamAt(Date.now())
      toast.success(`Red-team suite: ${data.blocked_attacks}/${data.total_attacks} attacks blocked`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Red-team run failed')
    } finally {
      setRedteamRunning(false)
    }
  }

  const commands = useMemo<CommandPaletteItem[]>(
    () => [
      {
        id: 'run-redteam',
        label: 'Run the red-team suite',
        group: 'Run',
        keywords: 'guardrails attacks safety',
        onSelect: () => setConfirmOpen(true),
      },
    ],
    [],
  )
  useCommands('evaluation-safety', commands)

  const visibleEntries = useMemo(
    () => (entries ?? []).filter((e) => !trippedOnly || e.decision !== 'allow'),
    [entries, trippedOnly],
  )

  const ruleColumns: Column<AuditRuleSummary>[] = [
    { key: 'layer', header: 'Layer', sortValue: (r) => r.layer, render: (r) => <Badge variant="outline">{r.layer}</Badge> },
    { key: 'rule', header: 'Rule', sortValue: (r) => r.rule, render: (r) => <span className="font-medium">{r.rule}</span> },
    { key: 'total', header: 'Decisions', align: 'right', sortValue: (r) => r.total, render: (r) => r.total },
    { key: 'block', header: 'Blocked', align: 'right', sortValue: (r) => r.block, render: (r) => r.block },
    { key: 'redact', header: 'Redacted', align: 'right', sortValue: (r) => r.redact, render: (r) => r.redact },
    { key: 'escalate', header: 'Escalated', align: 'right', sortValue: (r) => r.escalate, render: (r) => r.escalate },
    {
      key: 'trip',
      header: 'Trip rate',
      tip: 'Share of this rule’s decisions that were anything other than "allow".',
      sortValue: (r) => r.trip_rate,
      render: (r) => <InlineBar value={r.trip_rate} className="min-w-32" />,
    },
  ]

  const auditColumns: Column<AuditEntry>[] = [
    { key: 'when', header: 'When', sortValue: (e) => e.id, render: (e) => <span title={dateTime(e.created_at)}>{relativeTime(e.created_at)}</span> },
    { key: 'layer', header: 'Layer', sortValue: (e) => e.layer, render: (e) => <Badge variant="outline">{e.layer}</Badge> },
    { key: 'rule', header: 'Rule', sortValue: (e) => e.rule, render: (e) => e.rule },
    {
      key: 'decision',
      header: 'Decision',
      sortValue: (e) => e.decision,
      render: (e) => <Badge variant={DECISION_VARIANT[e.decision] ?? 'outline'}>{e.decision}</Badge>,
    },
    {
      key: 'score',
      header: 'Score',
      align: 'right',
      tip: 'The classifier’s confidence, where the rule has one. Regex rules have no score.',
      sortValue: (e) => e.score,
      render: (e) => (e.score === null ? <span className="text-muted-foreground">—</span> : e.score.toFixed(2)),
    },
    {
      key: 'excerpt',
      header: 'Excerpt',
      render: (e) => <span className="block max-w-md truncate text-muted-foreground" title={e.redacted_excerpt ?? undefined}>{e.redacted_excerpt ?? '—'}</span>,
    },
  ]

  const categoryRows: CategoryRow[] = redteam
    ? Object.entries(redteam.by_category).map(([category, stats]) => ({ category, ...stats }))
    : []
  const categoryColumns: Column<CategoryRow>[] = [
    { key: 'category', header: 'Attack category', sortValue: (r) => r.category, render: (r) => <span className="font-medium">{r.category.replace(/_/g, ' ')}</span> },
    { key: 'blocked', header: 'Blocked', align: 'right', sortValue: (r) => r.blocked, render: (r) => `${r.blocked} / ${r.total}` },
    { key: 'rate', header: 'Block rate', term: 'block_rate', sortValue: (r) => r.block_rate, render: (r) => <InlineBar value={r.block_rate} className="min-w-32" /> },
  ]

  const tripped = summary ? summary.total - (summary.by_decision.allow ?? 0) : undefined

  return (
    <div className="flex flex-col gap-6" data-testid="eval-safety">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-xs text-muted-foreground">
          Every input, retrieval and output check made on real questions. Red-team and evaluation runs are counted separately and never mixed into these numbers.
        </p>
        <Button onClick={() => setConfirmOpen(true)} disabled={redteamRunning} data-testid="run-redteam-button">
          <ShieldAlert className="size-4" />
          {redteamRunning ? 'Running suite…' : 'Run red-team suite'}
        </Button>
      </div>

      {summaryError ? (
        <ErrorState error={summaryError} action={<Button size="sm" variant="outline" onClick={loadSummary}>Retry</Button>} />
      ) : (
        <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Decisions logged"
            tip="Every guardrail check on a real question, including the ones that passed."
            loading={summary === null}
            value={summary ? compact(summary.total) : undefined}
            caption={summary?.first_at ? `since ${dateTime(summary.first_at)}` : 'no real traffic yet'}
            testId="guardrails-kpi-total"
          />
          <StatCard
            label="Trip rate"
            tip="Share of decisions on real questions that blocked, redacted or escalated."
            loading={summary === null}
            value={summary && summary.trip_rate !== null ? pct(summary.trip_rate) : undefined}
            emptyLabel="No decisions yet"
            caption={tripped !== undefined ? `${tripped} of ${summary!.total}` : undefined}
          />
          <StatCard
            label="Blocked"
            loading={summary === null}
            value={summary ? (summary.by_decision.block ?? 0) : undefined}
            caption={summary ? `${summary.by_decision.redact ?? 0} redacted · ${summary.by_decision.escalate ?? 0} escalated` : undefined}
          />
          <StatCard
            label="Red-team block rate"
            term="block_rate"
            value={redteam ? pct(redteam.block_rate) : undefined}
            emptyLabel="Not run this session"
            caption={redteam && redteamAt ? `${redteam.blocked_attacks}/${redteam.total_attacks} attacks · ${relativeTime(redteamAt)}` : 'run the suite to measure'}
            testId="guardrails-kpi-redteam"
          />
        </div>
      )}

      <Panel
        title="Red-team suite"
        description="42 attack prompts in 5 categories and 15 harmless prompts, each sent through the real input guardrail. Passing needs a block rate of at least 95% and a false-positive rate of at most 10%."
        testId="redteam-panel"
      >
        {redteamRunning ? (
          <LoadingState shape="table" rows={5} label="Running the red-team suite" />
        ) : redteam ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
              <Badge variant={redteam.block_rate >= 0.95 ? 'success' : 'destructive'}>
                block rate {pct(redteam.block_rate)} {redteam.block_rate >= 0.95 ? '— passes' : '— below 95%'}
              </Badge>
              <Badge variant={redteam.false_positive_rate <= 0.1 ? 'success' : 'destructive'}>
                false positives {pct(redteam.false_positive_rate)} ({redteam.false_positives}/{redteam.total_benign})
              </Badge>
            </div>
            <DataTable
              caption="Red-team results by attack category"
              columns={categoryColumns}
              rows={categoryRows}
              rowKey={(r) => r.category}
              initialSort={{ key: 'rate', direction: 'asc' }}
              testId="redteam-results"
            />
          </div>
        ) : (
          <EmptyState
            title="The suite has not been run in this session"
            description="Results are measured, not stored: run it to see how the guardrails do right now."
            action={<Button size="sm" onClick={() => setConfirmOpen(true)}>Run red-team suite</Button>}
          />
        )}
      </Panel>

      <Panel
        title="Trips by rule"
        description="Which checks fire on real questions, and how often. A rule that never trips may be dead weight; one that trips constantly may be too strict."
      >
        {summary === null && !summaryError ? (
          <LoadingState shape="table" rows={4} label="Loading rule summary" />
        ) : (
          <DataTable
            caption="Guardrail decisions grouped by rule"
            columns={ruleColumns}
            rows={summary?.rules ?? []}
            rowKey={(r) => `${r.layer}/${r.rule}`}
            initialSort={{ key: 'trip', direction: 'desc' }}
            empty={<EmptyState title="No guardrail decisions yet" description="Ask a question in Workspace; every check it goes through is logged here." />}
            testId="guardrail-rules"
          />
        )}
      </Panel>

      <Panel
        title="Audit log"
        description="The latest 200 decisions on real questions, newest first. Excerpts are stored after PII masking."
        actions={
          <>
            <Segmented
              label="Filter by layer"
              value={layer}
              onChange={setLayer}
              options={[
                { value: 'all', label: 'All' },
                { value: 'input', label: 'Input' },
                { value: 'retrieval', label: 'Retrieval' },
                { value: 'output', label: 'Output' },
              ]}
            />
            <Button size="sm" variant={trippedOnly ? 'default' : 'outline'} aria-pressed={trippedOnly} onClick={() => setTrippedOnly((v) => !v)}>
              Tripped only
            </Button>
          </>
        }
        testId="audit-log"
      >
        {entriesError ? (
          <ErrorState error={entriesError} action={<Button size="sm" variant="outline" onClick={loadEntries}>Retry</Button>} />
        ) : entries === null ? (
          <LoadingState shape="table" rows={6} label="Loading audit log" />
        ) : (
          <DataTable
            caption="Guardrail audit log"
            columns={auditColumns}
            rows={visibleEntries}
            rowKey={(e) => String(e.id)}
            empty={<EmptyState title={entries.length === 0 ? 'Nothing logged for this layer yet' : 'No tripped decisions in this view'} />}
          />
        )}
      </Panel>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Run the red-team suite?"
        description="Sends 57 prompts through the input guardrail one after another, including the Llama Guard model when Ollama is up."
        cost="Typically one to three minutes on local hardware, and it keeps the guard model busy while it runs."
        confirmLabel="Run suite"
        onConfirm={() => void handleRedteam()}
      />
    </div>
  )
}
