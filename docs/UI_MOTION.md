# UI Motion

How animation is implemented across the Veritas frontend, component by component. This file
starts with the component-library phase (design system + `src/components/ui/`); later phases
(the real app screens, the landing page) append their own sections below rather than rewriting
this one.

Shared infrastructure these all build on:

- **`frontend/src/lib/motion.ts`** — the one source of truth for durations/springs/eases used
  from JS. Mirrors the CSS tokens in `src/index.css` (`--duration-120/240/480/800`,
  `--ease-spring`, `--ease-out`) as actual seconds/easing-array values Framer Motion can consume:
  `DURATION.fast/base/slow/slower` (0.12/0.24/0.48/0.8s), `SPRING` (`{ stiffness: 300, damping:
  20, mass: 0.9 }`, used for small-travel feedback), `SPRING_SOFT` (`{ stiffness: 180, damping:
  24, mass: 1 }`, used for larger-travel motion), `EASE_OUT` (`[0.16, 1, 0.3, 1]`), and a
  `reducedTransition(reduced, transition)` helper that collapses any transition to ~0 duration.
- **Reduced motion** — the global CSS rule in `index.css` already forces every CSS
  transition/animation to ~0 duration. Every component below additionally calls Framer Motion's
  `useReducedMotion()` and branches its *JS-driven* transform animations on it (that CSS rule
  can't reach `animate()`/spring-driven transforms), per the brief. Components that are pure CSS
  (Skeleton's shimmer) rely on the global rule alone, since there's no JS animation to branch.
- **`frontend/src/lib/raf-loop.ts`** — a single shared `requestAnimationFrame` loop (subscribe/
  unsubscribe) for anything that needs genuinely continuous, frame-by-frame updates, explicitly
  cancelled on `document.visibilitychange` and restarted on return. Used by GlowCard's cursor
  glow (below). Button's magnetic offset and TiltCard's tilt do *not* use it — they only update
  on discrete pointer events via Framer Motion's own `useMotionValue.set()`, which batches
  through Framer Motion's internal shared scheduler; the explicit shared loop is reserved for the
  one effect that's genuinely frame-driven regardless of input events (the eased follow).

## Theme toggle (`components/ui/theme-toggle.tsx`)

A `motion.span` thumb slides between the two ends of the track via `animate={{ x: isLight ? 24 :
0 }}`, transitioned with the shared `SPRING` preset (wrapped in `reducedTransition`). The sun/moon
icon swap is a plain conditional render (no crossfade) to keep the one JS animation on this
component limited to the transform. The track itself and the two static icon hints either side of
it are plain CSS (`transition-colors duration-240`), since they're color-only state changes, not
transforms.

## Button (`components/ui/button.tsx`)

Magnetic hover: a `useMotionValue`-driven offset on `x`/`y`, computed from the pointer position
relative to the button's center on `onPointerMove`, scaled by a `0.35` pull factor and clamped to
±8px (`MAGNETIC_RANGE`/`MAGNETIC_PULL` constants) before being fed into `useSpring(..., SPRING)`
for the chase. Resets to `{x: 0, y: 0}` on `onPointerLeave`. Disabled entirely when
`useReducedMotion()` is true or the pointer is touch (`event.pointerType === 'touch'` — magnetic
pull doesn't make sense without a hover concept). A `whileTap={{ scale: 0.96 }}` gives tactile
press feedback, also skipped under reduced motion. The `asChild` path (rendering an arbitrary
child via Radix `Slot`) intentionally has none of this — magnetic transforms only make sense for
the literal `<button>`.

## Badge (`components/ui/badge.tsx`)

No Framer Motion — hover/focus states are plain CSS color transitions (`transition-all` from the
base shadcn classes). A badge is a static label; there's no meaningful motion to add beyond what
the color system already gives it via the `glow`/`success`/`warning` variants added on top of
shadcn's defaults.

## Card vs. GlowCard vs. TiltCard

`components/ui/card.tsx` is the plain shadcn structural primitive (no motion) — used as scaffolding
inside Dialog/Command and anywhere a flashy treatment would be noise. The two components with
actual visual-effect motion are separate, on top of it:

- **GlowCard (`components/ui/glow-card.tsx`)** — the "glass with a gradient border and
  cursor-follow glow" card. The gradient border is a CSS trick (padding + `background-image:
  var(--gradient-border)` on the outer element, a 1px-inset inner element on top), not animated.
  The glow is a `motion.div` with a radial-gradient background, translated via `style={{ x: glowX,
  y: glowY, translateX: '-50%', translateY: '-50%' }}` — pure `transform`, never top/left. Raw
  pointer position is captured on `onPointerMove` into a ref (not state, to avoid a re-render per
  mousemove); a callback subscribed to the shared `raf-loop` lerps `glowX`/`glowY` 18% of the way
  toward that target every frame (`LERP_FACTOR = 0.18`) for an eased trailing feel, and
  unsubscribes on `onPointerLeave`/unmount. Disabled under reduced motion (the glow element isn't
  rendered at all).
- **TiltCard (`components/ui/tilt-card.tsx`)** — 3D pointer tilt. `rotateX`/`rotateY` motion
  values (never width/height) computed from pointer position within the card (±10°,
  `MAX_TILT_DEG`), smoothed with `useSpring(..., SPRING_SOFT)`, applied to an inner
  `transformStyle: 'preserve-3d'` wrapper while the outer element carries `perspective: 800` and a
  `whileHover={{ scale: 1.02 }}` lift. Resets to 0 on pointer leave; skipped under reduced motion
  and for touch pointers.

## StatCard (`components/ui/stat-card.tsx`)

No motion of its own — it's a GlowCard composed with a label/value/delta layout and the
loading/empty/error/success contract (`ComponentStatus`). Its "loading" presentation reuses
Skeleton (see below); the point of this component is the state contract, not new motion.

## Gauge (`components/ui/gauge.tsx`)

SVG + Framer Motion, per the brief (deliberately not a chart library). The ring is two
concentric `<circle>` elements (a static track + a `motion.circle` with a linear gradient stroke);
the foreground circle's `strokeDashoffset` is bound to a `useTransform` of a `progress`
`useMotionValue` (`circumference * (1 - p)`). On mount/value change, `animate(progress, fraction,
{ duration: reduced ? 0 : 1, ease: EASE_OUT })` sweeps it, with an `onUpdate` callback that writes
the live percentage straight into a `ref`'d `<span>`'s `textContent` — not React state — so the
once-per-frame tick never triggers a React re-render. `formatValue` is memoized
(`useMemo(..., [formatValue])`) so its identity is stable across renders when the caller doesn't
pass a custom formatter, which matters because it's a real dependency of the sweep effect (an
unstable identity would restart the sweep on every unrelated re-render). The animated SVG/number
is `aria-hidden`; the real accessible value is `role="meter"` + `aria-valuenow/min/max` on the
container, so a screen reader gets the final value once, not every intermediate tick.

## Stepper (`components/ui/stepper.tsx`)

Two small transform-only animations: each step's indicator circle does `animate={{ scale:
state === 'active' ? 1.1 : 1 }}` (duration `DURATION.fast`, `EASE_OUT`); the connecting line
between two steps is a `motion.div` with `transformOrigin: 'left'` (horizontal) or `'top'`
(vertical) animated via `scaleX`/`scaleY` between 0 and 1 as steps complete — never the line's
actual `width`/`height`. Both branch on `useReducedMotion()` (duration drops to 0).

## Skeleton (`components/ui/skeleton.tsx`)

Deliberately **not** Framer Motion — a pure CSS `translateX` keyframe sweep (`.skeleton-shimmer`
in `index.css`, keyframe `skeleton-sweep`), chosen specifically because it's a `transform`-only
animation that runs on the compositor thread without needing any JS at all, and because the global
`prefers-reduced-motion` CSS rule already collapses any CSS `animation-duration` to ~0 — so this
one component's motion is fully handled by the CSS layer with zero extra JS branching needed.

## Drawer (`components/ui/drawer.tsx`)

Built on the Dialog primitive (`npx shadcn add dialog`), repositioned as a slide-over instead of a
centered modal. Radix's `forceMount` + an outer `<AnimatePresence>` hands the enter/exit
choreography to Framer Motion instead of Dialog's own CSS fade/zoom (the pattern Radix's own docs
recommend for pairing with an external animation library). Since `Dialog.Root`'s resolved `open`
state isn't otherwise readable by a descendant, a small `DrawerOpenContext` mirrors it so
`DrawerContent` can gate `<AnimatePresence>{open && (...)}</AnimatePresence>` on the same value
driving the Radix side. The panel slides via `x`/`y` (±100%, per side) with the `SPRING_SOFT`
preset; the overlay fades via `opacity`. Both initial/animate/exit collapse to an opacity-only
fade under reduced motion rather than a transform.

## Dialog, Tooltip, Command primitives

Left on Radix's own built-in open/close choreography — `data-[state]`-driven CSS classes
(`animate-in`/`fade-in-0`/`zoom-in-95`/`slide-in-from-*`, provided by the `tw-animate-css`
dependency shadcn's generator wired in) rather than re-implemented in Framer Motion. These are
plain CSS transitions, so the global `prefers-reduced-motion` rule already shortens them to ~0;
there's no JS-driven transform here to separately branch. This is an intentional split: Framer
Motion is used where this document shows a genuine need for spring physics, pointer-driven
transforms, or coordinating with React state (magnetic buttons, tilt, the glow, Drawer, the
counted-up Gauge) — not as a blanket replacement for every CSS transition.

## Toast (`components/ui/sonner.tsx`)

Wraps `sonner`, which has its own built-in enter/exit/swipe-to-dismiss animation (also plain CSS,
not Framer Motion). What's custom here is purely visual theming: `theme` is read from
`useTheme()` instead of `next-themes` (see docs/DECISIONS.md), and `--normal-bg`/`--success-bg`/
`--warning-bg`/`--error-bg` etc. are remapped to this app's own tokens via inline `style` CSS
variables so toasts match the glass/tint aesthetic instead of sonner's generic defaults.

## Command palette (`components/ui/command-palette.tsx`)

The palette itself is a `CommandDialog` (so it inherits the Dialog/Radix CSS entrance above); the
custom part is the `Cmd/Ctrl+K` global `keydown` listener (`CommandPaletteProvider`) and `cmdk`'s
own internal list-filtering, which has no custom motion applied — cmdk's selected-item highlight
is an instant background-color change, intentionally not animated, so keyboard navigation through
results feels immediate rather than laggy.

## Section reveal (`components/showcase/component-showcase.tsx`)

The showcase (not a component itself) staggers each section in with `whileInView={{ opacity: 1,
y: 0 }}` from `{ opacity: 0, y: 24 }`, `viewport={{ once: true, margin: '-80px' }}`,
`DURATION.slow`/`EASE_OUT` — `transform`(`y`)/`opacity` only, and skipped entirely (both `initial`
and `whileInView` left `undefined`) under reduced motion so sections simply render in place.

## Smooth scroll (`lib/smooth-scroll.tsx`) and GSAP

Lenis wraps the whole app (`<ReactLenis root>`, from the `lenis/react` subpath) for inertia
scrolling, with `lerp: 0.1` — skipped entirely under reduced motion (renders children with no
Lenis wrapper at all, falling back to native scroll), since smooth-scroll hijacking is itself a
motion effect a "reduce motion" preference should turn off, not shorten. **GSAP is installed but
intentionally unused in this phase** — the brief scopes `ScrollTrigger` to the landing page, which
doesn't exist yet (a later phase owns it); wiring it into the component showcase or any other
screen now would be using it somewhere the brief didn't ask for it.

## "Later phase" preview tiles (`components/showcase/future-phase-previews.tsx`)

Not components, and not animated by this codebase — `@xyflow/react` (`fitView`, no drag/connect/
select, since these are static previews), `react-force-graph-2d` (its own physics-based force
simulation, settled via `onEngineStop` → `zoomToFit`) and ECharts (`animationDuration: 400` on the
line series) each run their own internal animation systems. They're included only as a smoke test
that the three libraries the brief's STACK section requires actually render on React 19 — see
docs/DECISIONS.md for why they're lazy-loaded out of the main bundle.

## Real app screens (`src/pages/*`, `src/components/layout/app-shell.tsx`)

The actual Veritas screens that replaced `App.tsx`'s design-system showcase (see
docs/DECISIONS.md's frontend-phase entry for the scope line on this phase). Motion here is
overwhelmingly *reuse*, not new choreography — every page composes the components documented
above (Stepper, Gauge, GlowCard, TiltCard, Drawer, StatCard) exactly as built, with their
existing reduced-motion handling unchanged. The only genuinely new motion in this phase:

- **Architecture tab's `StageNode`** (`pages/architecture-page.tsx`) — the one custom animated
  primitive this phase adds. A `motion.button` (one per real pipeline stage) runs `animate={{
  scale: [1, 1.06, 1] }}` on an infinite `duration: 1.1` loop *only* while that stage's latest
  real `TraceEvent.status` is `"running"` — the animation target is derived directly from live
  WebSocket data, not a local timer, so a stage that's actually idle or already done never
  pulses. Does not yet branch on `useReducedMotion()` — a real gap, not a deliberate choice;
  see docs/VALIDATION_REPORT.md's accessibility section.
- **Ingestion Theater** reuses `Stepper` as-is, feeding it real `StepState`s derived from the
  same live trace events (`stageState()` in `pages/workspace-page.tsx` maps a `TraceEvent`'s
  `status` to `pending|active|complete|error`) — this is exactly the "drive Stepper from a real
  pipeline" use case the component was already built for, just connected to data for the first
  time in this phase.
- **Chat message entry** has no entrance animation — new `MessageBubble`s simply appear.
  Streaming tokens arrive many times a second during an answer; animating each append would
  fight the SSE stream rather than read as "typing." Explicitly not addressed with a
  per-character typewriter effect either — out of scope for this phase, noted rather than
  silently skipped.
- **Landing page** reuses `TiltCard` for the feature grid and the existing `Button`/
  `ThemeToggle` as-is; it has no GSAP `ScrollTrigger` Cinematic Tour and no hero video. GSAP
  remains installed-but-unused for the same reason the design-system phase gave: the feature
  that would use it was never built this session — see docs/VALIDATION_REPORT.md.

## Ingestion reliability pass (docs/TROUBLESHOOTING.md)

Ingestion became a real async job (queued/running/ready/failed/cancelled) instead of one
blocking call, which needed new progress/error UI. New motion, and one fix:

- **AlertBanner (`components/ui/alert-banner.tsx`)** — the one genuinely new animated
  primitive this pass adds, used for both the ingestion error/cancelled state and the shell's
  preflight-degraded banner. A plain `motion.div` enter/exit (`opacity`+`y`, never
  width/height), gated through `reducedTransition()` like every other JS-driven transform in
  this document. The caller wraps it in its own `<AnimatePresence>` so the exit plays when the
  condition clears (a check starts passing, a job is retried) rather than the element just
  vanishing. No pulse/loop motion — a persistent condition banner shouldn't visually nag.
- **Workspace's ingestion Stepper** gets no new motion of its own — it's still exactly the
  `Stepper` documented above, just fed a richer `stageState()` that now falls back to the
  polled document snapshot (`current_stage`/`status`/`enrichment_status`) when the trace
  WebSocket has delivered nothing yet, so the existing per-step scale/line-fill animations
  keep working even if the socket never connects.
- **StageNode reduced-motion fix** — the Architecture tab's per-stage pulse (documented above
  as a known gap: "does not yet branch on `useReducedMotion()`") now does:
  `isActive = data.status === 'running' && !reduced`. Same component, same animation, the one
  line of handling that was missing.


## Motion language after the overhaul

One set of durations and one entrance curve, defined once in `src/styles/tokens.css` and
mirrored in `src/lib/motion.ts`: **120 ms** micro (hover, press), **200 ms** standard (panels,
list rows), **320 ms** large (page and tab changes), all on `cubic-bezier(0.32, 0.72, 0, 1)`.
Lists stagger 30 ms apart for the first ten rows only. Only `transform` and `opacity` are
animated on recurring motion.

| Where | Motion | Driven by |
| --- | --- | --- |
| Top navigation, Evaluation views | A pill slides between tabs (shared layout) | Navigation |
| Analyst robot | Idle hover, working scan, success and error poses | Real ingest / answer state |
| Answers | Text appears as the model writes it; scoring shows a skeleton | Token stream |
| KPI cards | Numbers count up when the value changes meaningfully | New data |
| Charts | Draw in once, when first scrolled into view | Visibility |
| Architecture packets, node ripple and bloom | A packet per real hop, speed from measured latency | Trace events only |
| Architecture edge dashes, aurora backdrop | Slow ambient drift | Decoration — stated in the legend |
| "Play request path" | Steps through declared request edges | A button; labelled an illustration |
| Knowledge graph | Particle torus; entities light up in traversal order | A real graph query |

`prefers-reduced-motion` collapses CSS animation globally (`index.css`) and every Framer
Motion transition checks `useReducedMotion`; packets, ripples and chart animation are skipped
while state changes still show.

Added in the second pass: cards and panels rise in with a 45 ms stagger (`.rise-in`,
`.stagger`); a sheen crosses a KPI card on hover; healthy status dots emit a slow halo; the
Deep reasoning button breathes while on; an answer being written ends in a caret; the
Architecture canvas has a drifting blueprint grid and a scan line that sweeps once on load, on
a view change and when a walkthrough starts; the walkthrough sends a three-packet stream per
hop; nodes lift on hover. All of it is decoration except the caret (real streaming) and the
status halo (a probe that really returned healthy).
