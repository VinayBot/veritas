import { NavLink, Outlet, Link, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Command as CommandIcon, FlaskConical, MessageSquare, Workflow, type LucideIcon } from 'lucide-react'
import { ThemeToggle } from '@/components/ui/theme-toggle'
import { Badge } from '@/components/ui/badge'
import { AlertBanner } from '@/components/ui/alert-banner'
import { useCommandPalette, useCommands, type CommandPaletteItem } from '@/components/ui/command-palette'
import { DocumentSwitcher } from './document-switcher'
import { usePolling } from '@/hooks/usePolling'
import { cn } from '@/lib/utils'
import { SPRING_SOFT } from '@/lib/motion'
import { getDocument, getHealth } from '@/lib/api/client'
import { ApiError, type HealthResponse } from '@/lib/api/types'
import { useAppStore } from '@/store/app-store'

export const NAV_ITEMS: { to: string; label: string; icon: LucideIcon; end: boolean }[] = [
  { to: '/app', label: 'Workspace', icon: MessageSquare, end: true },
  { to: '/app/architecture', label: 'Architecture', icon: Workflow, end: false },
  { to: '/app/evaluation', label: 'Evaluation', icon: FlaskConical, end: false },
]

function HealthBadge({ health, failed }: { health: HealthResponse | null; failed: boolean }) {
  if (failed) return <Badge variant="destructive">backend unreachable</Badge>
  if (!health) return <Badge variant="outline">checking…</Badge>
  const ollamaUp = health.ollama.status === 'up'
  return (
    <Badge variant={ollamaUp ? 'success' : 'warning'} title={health.ollama.models.join(', ')}>
      ollama {health.ollama.status} · {health.ollama.models.length} model
      {health.ollama.models.length === 1 ? '' : 's'}
    </Badge>
  )
}

/** Startup preflight warms every model and checks stores (backend/app/core/preflight.py);
 * this surfaces a failure immediately instead of mid-upload. Dismissible per session; a newly
 * failing check brings it back. */
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

/** A persisted document id is only a hint. Confirm it still exists; clear it if not. */
function useValidatedDocument() {
  const { documentId, setDocument } = useAppStore()
  useEffect(() => {
    if (!documentId) return
    let cancelled = false
    getDocument(documentId)
      .then((doc) => !cancelled && setDocument(doc.id, doc.filename))
      .catch((err) => {
        if (!cancelled && err instanceof ApiError && err.status === 404) setDocument(null, null)
      })
    return () => {
      cancelled = true
    }
    // Validate once per id, not on every store change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId])
}

export function AppShell() {
  const { data: health, error } = usePolling(getHealth, { intervalMs: 15_000 })
  const { setOpen: setPaletteOpen } = useCommandPalette()
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const navigate = useNavigate()
  const reduced = useReducedMotion()
  useValidatedDocument()

  const commands = useMemo<CommandPaletteItem[]>(
    () => [
      ...NAV_ITEMS.map(({ to, label, icon: Icon }) => ({
        id: `go-${label.toLowerCase().replace(/\s+/g, '-')}`,
        label: `Go to ${label}`,
        icon: <Icon className="size-4" />,
        group: 'Navigate',
        onSelect: () => navigate(to),
      })),
      {
        id: 'switch-document',
        label: 'Switch document…',
        group: 'Navigate',
        keywords: 'corpus file',
        onSelect: () => setSwitcherOpen(true),
      },
    ],
    [navigate],
  )
  useCommands('shell', commands)

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-sm focus:text-on-accent"
      >
        Skip to content
      </a>
      <header className="relative z-(--z-sticky) flex h-14 shrink-0 items-center gap-4 border-b border-border bg-surface/80 px-4 backdrop-blur-(--blur-glass)">
        <Link to="/" className="flex shrink-0 items-center gap-2">
          <span aria-hidden="true" className="flex size-7 items-center justify-center rounded-lg bg-accent font-display text-sm font-bold text-on-accent shadow-glow">
            真
          </span>
          <span className="font-display text-lg font-semibold tracking-tight text-foreground">Veritas</span>
        </Link>
        <nav aria-label="Primary" className="flex items-center gap-1 rounded-xl border border-border bg-background/60 p-1">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'relative flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors duration-micro',
                  isActive ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId="nav-pill"
                      aria-hidden="true"
                      className="absolute inset-0 rounded-lg bg-accent/20 shadow-[inset_0_-2px_0_var(--color-accent)]"
                      transition={reduced ? { duration: 0 } : SPRING_SOFT}
                    />
                  )}
                  <Icon className="relative size-4 shrink-0" aria-hidden="true" />
                  <span className="relative">{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex min-w-0 items-center gap-2.5">
          <div className="hidden w-60 min-w-0 md:block">
            <DocumentSwitcher open={switcherOpen} onOpenChange={setSwitcherOpen} />
          </div>
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            aria-label="Open the command palette"
            className="hidden items-center gap-2 rounded-lg border border-border px-2.5 py-1.5 text-xs text-muted-foreground transition-colors duration-micro hover:text-foreground sm:flex"
          >
            <CommandIcon className="size-3.5" aria-hidden="true" />
            <kbd className="font-sans text-[10px]">⌘K</kbd>
          </button>
          <HealthBadge health={health} failed={error !== null} />
          <ThemeToggle />
        </div>
      </header>
      <main id="main" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
        <PreflightBanner health={health} />
        <Outlet />
      </main>
    </div>
  )
}
