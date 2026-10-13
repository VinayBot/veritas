import { Suspense, lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider } from '@/lib/theme'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { CommandPaletteProvider } from '@/components/ui/command-palette'
import { AppShell } from '@/components/layout/app-shell'
import { LandingPage } from '@/pages/landing-page'
import { WorkspacePage } from '@/pages/workspace-page'
import { LoadingState } from '@/components/ui/loading-state'

// The diagram and chart libraries are large; each tab loads its own on first visit.
const ArchitecturePage = lazy(() => import('@/pages/architecture-page').then((m) => ({ default: m.ArchitecturePage })))
const EvaluationPage = lazy(() => import('@/pages/evaluation-page').then((m) => ({ default: m.EvaluationPage })))
const tabFallback = <LoadingState shape="cards" rows={4} label="Loading" className="p-6" />

function App() {
  return (
    <ThemeProvider>
      <TooltipProvider delayDuration={150}>
        <BrowserRouter>
          <CommandPaletteProvider>
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route element={<AppShell />}>
                <Route path="/app" element={<WorkspacePage />} />
                <Route path="/app/architecture" element={<Suspense fallback={tabFallback}><ArchitecturePage /></Suspense>} />
                <Route path="/app/evaluation" element={<Suspense fallback={tabFallback}><EvaluationPage /></Suspense>} />
                {/* Three tabs only. Former tabs land on the Evaluation view that absorbed them. */}
                <Route path="/app/dashboard" element={<Navigate to="/app/evaluation" replace />} />
                <Route path="/app/graph" element={<Navigate to="/app/evaluation?view=graph" replace />} />
                <Route path="/app/guardrails" element={<Navigate to="/app/evaluation?view=safety" replace />} />
                <Route path="/app/test-center" element={<Navigate to="/app/architecture" replace />} />
                <Route path="/app/*" element={<Navigate to="/app" replace />} />
              </Route>
            </Routes>
          </CommandPaletteProvider>
        </BrowserRouter>
        <Toaster position="bottom-right" />
      </TooltipProvider>
    </ThemeProvider>
  )
}

export default App
