import { NavLink, Outlet, Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { MessageSquare, Workflow, Share2, FlaskConical, Wrench } from 'lucide-react'
import { ThemeToggle } from '@/components/ui/theme-toggle'
import { Badge } from '@/components/ui/badge'
import { AlertBanner } from '@/components/ui/alert-banner'
import { cn } from '@/lib/utils'
import { getHealth } from '@/lib/api/client'
import type { HealthResponse } from '@/lib/api/types'

const NAV_ITEMS = [
  { to: '/app', label: 'Workspace', icon: MessageSquare, end: true },
  { to: '/app/architecture', label: 'Architecture', icon: Workflow, end: false },
  { to: '/app/graph', label: 'Knowledge Graph', icon: Share2, end: false },
  { to: '/app/evaluation', label: 'Evaluation', icon: FlaskConical, end: false },
  { to: '/app/test-center', label: 'Test Center', icon: Wrench, end: false },
]

/** Lifted into AppShell (rather than each caller polling separately) so the sidebar badge and
 * the preflight banner below share one /health poll instead of two independent intervals. */
function useBackendHealth(): { health: HealthResponse | null; failed: boolean } {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    const poll = () =>
      getHealth()
        .then((h) => {
          if (!cancelled) {
            setHealth(h)
            setFailed(false)
          }
        })
        .catch(() => {
          if (!cancelled) setFailed(true)
        })
    poll()
    const interval = window.setInterval(poll, 15_000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [])

  return { health, failed }
}

function HealthBadge({ health, failed }: { health: HealthResponse | null; failed: boolean }) {
  if (failed) return <Badge variant="destructive">backend unreachable</Badge>
  if (!health) return <Badge variant="outline">checking...</Badge>

  const ollamaUp = health.ollama.status === 'up'
  return (
    <Badge variant={ollamaUp ? 'success' : 'warning'} title={health.ollama.models.join(', ')}>
      ollama {health.ollama.status} · {health.ollama.models.length} model
      {health.ollama.models.length === 1 ? '' : 's'}
    </Badge>
  )
}

/** Startup preflight warms every model + checks Ollama/vector-store reachability (see
 * backend/app/core/preflight.py and docs/TROUBLESHOOTING.md) — this surfaces the result so a
 * missing model is visible immediately instead of discovered mid-upload. Dismissible per
 * session; a newly-failing check (or a fresh preflight re-run) brings it back. */
function PreflightBanner({ health }: { health: HealthResponse | null }) {
  const [dismissed, setDismissed] = useState(false)
  const preflight = health?.preflight
  const degraded = preflight && preflight.status === 'degraded' ? preflight : null
  const failingChecksKey = degraded?.checks.map((c) => c.name + c.ok).join(',') ?? ''

  useEffect(() => {
    setDismissed(false)
  }, [failingChecksKey])

  return (
    <AnimatePresence>
      {degraded && !dismissed && (
        <AlertBanner
          variant="warning"
          title="Some backend checks failed at startup"
          description={degraded.checks
            .filter((c) => !c.ok)
            .map((c) => `${c.name}: ${c.detail}`)
            .join(' · ')}
          onDismiss={() => setDismissed(true)}
          className="mx-6 mt-4"
        />
      )}
    </AnimatePresence>
  )
}

export function AppShell() {
  const { health, failed } = useBackendHealth()

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface">
        <Link to="/" className="flex items-center gap-2 px-5 py-5">
          <span className="font-display text-lg font-semibold tracking-tight text-foreground">
            Veritas
          </span>
        </Link>
        <nav className="flex flex-1 flex-col gap-1 px-3">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors duration-150',
                  'hover:bg-muted hover:text-foreground',
                  isActive && 'bg-accent/10 text-accent-soft',
                )
              }
            >
              <Icon className="size-4 shrink-0" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-4">
          <HealthBadge health={health} failed={failed} />
          <ThemeToggle />
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <PreflightBanner health={health} />
        <Outlet />
      </main>
    </div>
  )
}
