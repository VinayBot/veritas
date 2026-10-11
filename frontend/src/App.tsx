import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider } from '@/lib/theme'
import { SmoothScroll } from '@/lib/smooth-scroll'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { CommandPaletteProvider } from '@/components/ui/command-palette'
import { AppShell } from '@/components/layout/app-shell'
import { LandingPage } from '@/pages/landing-page'
import { WorkspacePage } from '@/pages/workspace-page'
import { ArchitecturePage } from '@/pages/architecture-page'
import { KnowledgeGraphPage } from '@/pages/knowledge-graph-page'
import { EvaluationPage } from '@/pages/evaluation-page'
import { TestCenterPage } from '@/pages/test-center-page'
import { RobotPreviewPage } from '@/pages/_robot-preview-page'

function App() {
  return (
    <ThemeProvider>
      <SmoothScroll>
        <TooltipProvider>
          <CommandPaletteProvider>
            <BrowserRouter>
              <Routes>
                <Route path="/" element={<LandingPage />} />
                <Route path="/_robot-preview" element={<RobotPreviewPage />} />
                <Route element={<AppShell />}>
                  <Route path="/app" element={<WorkspacePage />} />
                  {/* Dashboard's content (advisor arena, per-answer report) moved into the
                      Workspace panel — see docs/DECISIONS.md TASK 3/4. Old links/bookmarks
                      still land somewhere real instead of a dead route. */}
                  <Route path="/app/dashboard" element={<Navigate to="/app" replace />} />
                  <Route path="/app/architecture" element={<ArchitecturePage />} />
                  <Route path="/app/graph" element={<KnowledgeGraphPage />} />
                  <Route path="/app/evaluation" element={<EvaluationPage />} />
                  <Route path="/app/test-center" element={<TestCenterPage />} />
                  {/* Guardrails' content moved out — the red-team suite into Evaluation's
                      Safety card, the audit log into Architecture's per-node drawer (see
                      docs/DECISIONS.md). Old links/bookmarks still land somewhere real. */}
                  <Route path="/app/guardrails" element={<Navigate to="/app/evaluation" replace />} />
                </Route>
              </Routes>
            </BrowserRouter>
            <Toaster position="bottom-right" />
          </CommandPaletteProvider>
        </TooltipProvider>
      </SmoothScroll>
    </ThemeProvider>
  )
}

export default App
