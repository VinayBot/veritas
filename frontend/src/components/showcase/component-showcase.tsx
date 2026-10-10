import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import {
  Bell,
  Code2,
  Database,
  Network,
  Rocket,
  Search,
  Sparkles,
  Workflow,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { GlowCard } from '@/components/ui/glow-card'
import { TiltCard } from '@/components/ui/tilt-card'
import { StatCard } from '@/components/ui/stat-card'
import { Gauge } from '@/components/ui/gauge'
import { Stepper, type StepperStep } from '@/components/ui/stepper'
import { Skeleton } from '@/components/ui/skeleton'
import { Separator } from '@/components/ui/separator'
import { ThemeToggle } from '@/components/ui/theme-toggle'
import { useCommandPalette } from '@/components/ui/command-palette'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from '@/components/ui/drawer'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { DURATION, EASE_OUT } from '@/lib/motion'
import type { ComponentStatus } from '@/components/ui/state-message'

// @xyflow/react, react-force-graph-2d and echarts are the heaviest
// dependencies in this app by far, and this section is the only thing that
// touches them — split them into their own chunk instead of growing the
// main bundle for three placeholder tiles. (All three `lazy()` calls import
// the same module, so they share one chunk, loaded once.)
const FlowPreview = lazy(() =>
  import('./future-phase-previews').then((m) => ({ default: m.FlowPreview })),
)
const GraphPreview = lazy(() =>
  import('./future-phase-previews').then((m) => ({ default: m.GraphPreview })),
)
const ChartPreview = lazy(() =>
  import('./future-phase-previews').then((m) => ({ default: m.ChartPreview })),
)

const isApplePlatform =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.platform)

// ---------------------------------------------------------------------------
// Live backend health check — the one piece of real (non-illustrative) data
// in this showcase. Everything else below uses clearly-labelled example
// props; this fetches /api/v1/health for real, same as the Phase-1 App.tsx
// scaffold did, so its loading/error/success states are genuine, not staged.
// ---------------------------------------------------------------------------
interface HealthResponse {
  status: string
  app_env: string
  hardware_tier: string
  ollama: { status: string; models: string[] }
  vector_store: string
  graph_store: string
}

function useBackendHealth() {
  const [status, setStatus] = useState<ComponentStatus>('loading')
  const [data, setData] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/v1/health', { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<HealthResponse>
      })
      .then((health) => {
        setData(health)
        setStatus('success')
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') return
        setError(err.message)
        setStatus('error')
      })
    return () => controller.abort()
  }, [])

  return { status, data, error }
}

// ---------------------------------------------------------------------------
// Small local layout helpers
// ---------------------------------------------------------------------------
function Section({
  id,
  title,
  description,
  children,
}: {
  id: string
  title: string
  description?: string
  children: ReactNode
}) {
  const reduced = useReducedMotion()
  return (
    <motion.section
      id={id}
      className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-6"
      initial={reduced ? undefined : { opacity: 0, y: 24 }}
      whileInView={reduced ? undefined : { opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: DURATION.slow, ease: EASE_OUT }}
    >
      <h2 className="font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
        {title}
      </h2>
      {description && <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{description}</p>}
      <div className="mt-6">{children}</div>
    </motion.section>
  )
}

function Row({ label, value, tone }: { label: string; value: string; tone?: ComponentStatus }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>
        <Badge
          variant={tone === 'error' ? 'destructive' : tone === 'success' ? 'success' : 'outline'}
        >
          {value}
        </Badge>
      </dd>
    </div>
  )
}

const GAUGE_STATES: { status: ComponentStatus; value: number; label: string }[] = [
  { status: 'success', value: 72, label: 'Retrieval precision' },
  { status: 'success', value: 94, label: 'Guardrail pass rate' },
  { status: 'loading', value: 0, label: 'Latency budget' },
  { status: 'empty', value: 0, label: 'Cost per query' },
]

const STAT_STATES: { status: ComponentStatus; label: string; value: string; delta?: string }[] = [
  { status: 'success', label: 'Avg. latency', value: '842 ms', delta: '-6% vs last run' },
  { status: 'loading', label: 'Tokens / query', value: '' },
  { status: 'empty', label: 'A/B deployments', value: '' },
  { status: 'error', label: 'Eval suite', value: '' },
]

const STEPPER_SUCCESS: StepperStep[] = [
  { id: 'ingest', title: 'Ingest', description: 'Chunk + embed', state: 'complete' },
  { id: 'retrieve', title: 'Retrieve', description: 'Hybrid search', state: 'complete' },
  { id: 'reason', title: 'Reason', description: 'Agentic plan', state: 'active' },
  { id: 'respond', title: 'Respond', description: 'Stream answer', state: 'pending' },
]

const STEPPER_ERROR_STEPS: StepperStep[] = [
  { id: 'ingest', title: 'Ingest', state: 'complete' },
  { id: 'retrieve', title: 'Retrieve', state: 'complete' },
  { id: 'reason', title: 'Reason', description: 'Guardrail blocked', state: 'error' },
  { id: 'respond', title: 'Respond', state: 'pending' },
]

export function ComponentShowcase() {
  const health = useBackendHealth()
  const { setOpen: setPaletteOpen } = useCommandPalette()
  const [dialogOpen, setDialogOpen] = useState(false)

  return (
    <div className="min-h-screen bg-background">
      {/* ----------------------------------------------------------- Header */}
      <header className="sticky top-0 z-[var(--z-sticky)] border-b border-border bg-[color-mix(in_srgb,var(--color-background)_80%,transparent)] backdrop-blur-glass">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-on-accent">
              <Sparkles className="size-4" aria-hidden="true" />
            </span>
            <span className="font-display text-lg font-semibold tracking-tight">Veritas</span>
            <Badge variant="outline" className="ml-1 hidden sm:inline-flex">
              Design system
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPaletteOpen(true)}
              aria-label="Open command palette"
            >
              <Search className="size-4" aria-hidden="true" />
              <span className="hidden sm:inline">Command palette</span>
              <kbd className="ml-1 rounded border border-border bg-surface-raised px-1.5 py-0.5 text-[10px] tabular-nums text-muted-foreground">
                {isApplePlatform ? '⌘K' : 'Ctrl K'}
              </kbd>
            </Button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* -------------------------------------------------------------- Hero */}
      <section className="mx-auto w-full max-w-6xl px-4 pt-16 pb-8 sm:px-6">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: DURATION.slow, ease: EASE_OUT }}
        >
          <Badge variant="glow" className="mb-4">
            Adaptive agentic RAG
          </Badge>
          <h1 className="font-display text-hero font-semibold tracking-tight text-foreground">
            Veritas component library
          </h1>
          <p className="mt-4 max-w-xl text-base text-muted-foreground sm:text-lg">
            Dark-first, glass, gradient-glow building blocks for the Veritas platform — every
            component below supports loading, empty, error, and success presentations out of the
            box.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button size="lg">
              <Rocket className="size-4" aria-hidden="true" />
              Primary action
            </Button>
            <Button variant="outline" size="lg">
              Secondary
            </Button>
            <Button variant="ghost" size="lg">
              Ghost
            </Button>
          </div>
        </motion.div>
      </section>

      <Separator className="mx-auto max-w-6xl" />

      {/* ---------------------------------------------------- Live backend */}
      <Section
        id="live-status"
        title="Live backend status"
        description="The one real (non-illustrative) data source on this page — a genuine fetch to /api/v1/health, same as the Phase-1 scaffold."
      >
        <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
          <GlowCard>
            <h3 className="font-display text-sm font-semibold text-muted-foreground">
              /api/v1/health
            </h3>
            <dl className="mt-4 space-y-2.5">
              {health.status === 'loading' && (
                <div className="space-y-2.5">
                  <Skeleton className="h-5 w-full" />
                  <Skeleton className="h-5 w-full" />
                  <Skeleton className="h-5 w-3/4" />
                </div>
              )}
              {health.status === 'error' && (
                <p className="text-sm text-danger">Backend unreachable: {health.error}</p>
              )}
              {health.status === 'success' && health.data && (
                <>
                  <Row label="API" value={health.data.status} tone={health.data.status === 'ok' ? 'success' : 'error'} />
                  <Row
                    label="Ollama"
                    value={health.data.ollama.status}
                    tone={health.data.ollama.status === 'up' ? 'success' : 'error'}
                  />
                  <Row label="Hardware tier" value={health.data.hardware_tier} />
                  <Row label="Vector store" value={health.data.vector_store} />
                  <Row label="Graph store" value={health.data.graph_store} />
                </>
              )}
            </dl>
          </GlowCard>
          <StatCard
            label="Local models pulled"
            status={health.status}
            value={health.data?.ollama.models.length ?? 0}
            delta={health.data?.ollama.models.join(', ') || undefined}
            icon={<Database className="size-4" />}
            emptyDescription="No models pulled yet."
            errorDescription={health.error ?? undefined}
          />
        </div>
      </Section>

      {/* -------------------------------------------------------- Buttons */}
      <Section
        id="buttons"
        title="Button"
        description="Magnetic hover (useMotionValue-driven offset, clamped to ±8px) plus a spring press. Try hovering and clicking any of these."
      >
        <div className="flex flex-wrap items-center gap-3">
          <Button>Default</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="link">Link</Button>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button size="xs">Extra small</Button>
          <Button size="sm">Small</Button>
          <Button size="default">Default</Button>
          <Button size="lg">Large</Button>
          <Button size="icon" aria-label="Notifications">
            <Bell className="size-4" />
          </Button>
          <Button disabled>Disabled</Button>
        </div>
      </Section>

      {/* --------------------------------------------------------- Badges */}
      <Section id="badges" title="Badge">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>Default</Badge>
          <Badge variant="secondary">Secondary</Badge>
          <Badge variant="outline">Outline</Badge>
          <Badge variant="ghost">Ghost</Badge>
          <Badge variant="destructive">Destructive</Badge>
          <Badge variant="success">Success</Badge>
          <Badge variant="warning">Warning</Badge>
          <Badge variant="glow">Glow</Badge>
        </div>
      </Section>

      {/* ----------------------------------------------------------- Cards */}
      <Section
        id="cards"
        title="Card, GlowCard & TiltCard"
        description="Card is the plain shadcn structural primitive. GlowCard adds a gradient border and a cursor-trailing glow (shared rAF loop, eased). TiltCard adds a 3D pointer tilt (rotateX/rotateY only)."
      >
        <div className="grid gap-6 sm:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Plain Card</CardTitle>
              <CardDescription>The shadcn structural primitive.</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Used wherever a flashy treatment would be noise — inside dialogs, lists, etc.
              </p>
            </CardContent>
          </Card>
          <GlowCard>
            <h3 className="font-display text-base font-medium">GlowCard</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Move your cursor over this card — the glow eases toward the pointer.
            </p>
          </GlowCard>
          <TiltCard>
            <h3 className="font-display text-base font-medium">TiltCard</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Tilts toward the pointer in 3D. Settles back with a soft spring.
            </p>
          </TiltCard>
        </div>
      </Section>

      {/* ------------------------------------------------------- StatCard */}
      <Section
        id="stat-cards"
        title="StatCard (Card as a data display)"
        description="The four states every data-displaying component must support, via a status prop."
      >
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {STAT_STATES.map((s) => (
            <StatCard
              key={s.label}
              label={s.label}
              value={s.value}
              delta={s.delta}
              status={s.status}
              emptyDescription="Not configured yet."
              errorDescription="Could not reach the eval service."
            />
          ))}
        </div>
      </Section>

      {/* ----------------------------------------------------------- Gauge */}
      <Section
        id="gauge"
        title="Gauge"
        description="SVG + Framer Motion radial gauge — sweeps to its real value prop and counts up, written directly to the DOM so the tick doesn't re-render React."
      >
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {GAUGE_STATES.map((g) => (
            <div key={g.label} className="flex flex-col items-center gap-3">
              <Gauge value={g.value} status={g.status} label={g.label} />
              <Badge variant="outline" className="text-[10px] uppercase">
                {g.status}
              </Badge>
            </div>
          ))}
        </div>
      </Section>

      {/* --------------------------------------------------------- Stepper */}
      <Section
        id="stepper"
        title="Stepper"
        description="Per-step state (pending/active/complete/error) plus an overall status for the sequence itself."
      >
        <div className="space-y-10">
          <div>
            <p className="mb-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Success — mixed step states
            </p>
            <Stepper steps={STEPPER_SUCCESS} />
          </div>
          <div>
            <p className="mb-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Success — one step errored
            </p>
            <Stepper steps={STEPPER_ERROR_STEPS} />
          </div>
          <div className="grid gap-8 sm:grid-cols-2">
            <div>
              <p className="mb-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Loading
              </p>
              <Stepper steps={[]} status="loading" />
            </div>
            <div>
              <p className="mb-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Empty
              </p>
              <Stepper steps={[]} status="empty" emptyDescription="No pipeline configured." />
            </div>
          </div>
        </div>
      </Section>

      {/* -------------------------------------------------------- Skeleton */}
      <Section
        id="skeleton"
        title="Skeleton"
        description="A translateX shimmer sweep (never width/background-position) in a few representative shapes."
      >
        <div className="grid gap-6 sm:grid-cols-3">
          <div className="space-y-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
          <div className="flex items-center gap-3">
            <Skeleton className="size-12 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3.5 w-2/3" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </div>
          <Skeleton className="h-24 w-full rounded-[var(--radius-card)]" />
        </div>
      </Section>

      {/* ---------------------------------------------------------- Drawer */}
      <Section id="drawer" title="Drawer" description="Built on the Dialog primitive, repositioned as a slide-over and animated with Framer Motion instead of Dialog's default fade/zoom.">
        <div className="flex flex-wrap gap-3">
          {(['left', 'right', 'bottom'] as const).map((side) => (
            <Drawer key={side}>
              <DrawerTrigger asChild>
                <Button variant="outline" className="capitalize">
                  Open {side} drawer
                </Button>
              </DrawerTrigger>
              <DrawerContent side={side}>
                <DrawerHeader>
                  <DrawerTitle className="capitalize">{side} drawer</DrawerTitle>
                  <DrawerDescription>
                    Slides in from the {side}, built on the same Dialog primitive as the modal
                    below.
                  </DrawerDescription>
                </DrawerHeader>
                <p className="text-sm text-muted-foreground">
                  Example content goes here — forms, filters, detail panels, etc.
                </p>
                <DrawerFooter>
                  <DrawerClose asChild>
                    <Button variant="outline">Close</Button>
                  </DrawerClose>
                </DrawerFooter>
              </DrawerContent>
            </Drawer>
          ))}
        </div>
      </Section>

      {/* ---------------------------------------------------------- Dialog */}
      <Section id="dialog" title="Dialog">
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button variant="outline">Open dialog</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Example dialog</DialogTitle>
              <DialogDescription>
                The stock shadcn Dialog primitive, reconciled to the dark-first token set.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  setDialogOpen(false)
                  toast.success('Confirmed')
                }}
              >
                Confirm
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </Section>

      {/* --------------------------------------------------------- Tooltip */}
      <Section id="tooltip" title="Tooltip">
        <div className="flex flex-wrap gap-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="icon" aria-label="View source">
                <Code2 className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>View source</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="icon" aria-label="Knowledge graph">
                <Network className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Knowledge graph (later phase)</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="icon" aria-label="Pipeline">
                <Workflow className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Agentic pipeline</TooltipContent>
          </Tooltip>
        </div>
      </Section>

      {/* ----------------------------------------------------------- Toast */}
      <Section id="toast" title="Toast" description="Wraps sonner, themed to match (see src/components/ui/sonner.tsx).">
        <div className="flex flex-wrap gap-3">
          <Button variant="outline" onClick={() => toast('Default toast', { description: 'Just some information.' })}>
            Default
          </Button>
          <Button
            variant="outline"
            onClick={() => toast.success('Saved successfully', { description: 'Your changes were applied.' })}
          >
            Success
          </Button>
          <Button
            variant="outline"
            onClick={() => toast.warning('Review needed', { description: 'A guardrail flagged this response.' })}
          >
            Warning
          </Button>
          <Button
            variant="outline"
            onClick={() => toast.error('Request failed', { description: 'The backend returned a 500.' })}
          >
            Error
          </Button>
        </div>
      </Section>

      {/* -------------------------------------------------- Command palette */}
      <Section
        id="command-palette"
        title="Command palette"
        description="Wraps cmdk, bound globally to Cmd/Ctrl+K (see the header button, or just press it)."
      >
        <Button onClick={() => setPaletteOpen(true)}>
          <Search className="size-4" aria-hidden="true" />
          Open command palette
        </Button>
      </Section>

      {/* ---------------------------------------------------- Later phases */}
      <Section
        id="later-phases"
        title="Installed for later phases"
        description="@xyflow/react, react-force-graph-2d and ECharts are real dependencies already, smoke-tested below so any React 19 / build issue surfaces now — but the Architecture, Knowledge Graph and analytics screens themselves are a later phase someone else owns. Nothing here is a finished feature."
      >
        <Suspense
          fallback={
            <div className="grid gap-6 lg:grid-cols-3">
              <Skeleton className="h-56 w-full rounded-[var(--radius-card)]" />
              <Skeleton className="h-56 w-full rounded-[var(--radius-card)]" />
              <Skeleton className="h-56 w-full rounded-[var(--radius-card)]" />
            </div>
          }
        >
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="min-w-0">
              <p className="mb-2 truncate text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Architecture tab — later phase
              </p>
              <FlowPreview />
            </div>
            <div className="min-w-0">
              <p className="mb-2 truncate text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Knowledge graph — later phase
              </p>
              <GraphPreview />
            </div>
            <div className="min-w-0">
              <p className="mb-2 truncate text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Analytics chart — later phase
              </p>
              <ChartPreview />
            </div>
          </div>
        </Suspense>
      </Section>

      <footer className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6">
        <Separator className="mb-6" />
        <p className="text-xs text-muted-foreground">
          Veritas design system — component library phase. See docs/UI_MOTION.md and
          docs/DECISIONS.md for details.
        </p>
      </footer>
    </div>
  )
}
