import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ThemeProvider } from '@/lib/theme'
import { SmoothScroll } from '@/lib/smooth-scroll'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { CommandPaletteProvider } from '@/components/ui/command-palette'
import { AppShell } from '@/components/layout/app-shell'
import { LandingPage } from '@/pages/landing-page'
import { WorkspacePage } from '@/pages/workspace-page'
import { DashboardPage } from '@/pages/dashboard-page'
import { ArchitecturePage } from '@/pages/architecture-page'
import { KnowledgeGraphPage } from '@/pages/knowledge-graph-page'
import { EvaluationPage } from '@/pages/evaluation-page'
import { GuardrailsPage } from '@/pages/guardrails-page'
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
                  <Route path="/app/dashboard" element={<DashboardPage />} />
                  <Route path="/app/architecture" element={<ArchitecturePage />} />
                  <Route path="/app/graph" element={<KnowledgeGraphPage />} />
                  <Route path="/app/evaluation" element={<EvaluationPage />} />
                  <Route path="/app/guardrails" element={<GuardrailsPage />} />
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
