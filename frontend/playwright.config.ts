import { defineConfig, devices } from '@playwright/test'

/** Real E2E against a real backend — see tests/e2e/README.md for how to run these.
 * Playwright starts the Vite dev server itself; the FastAPI backend (with Ollama up) must
 * already be running (PLAYWRIGHT_BACKEND_PORT, default 8000), since these tests exercise the
 * real ingestion/chat/evaluation pipelines end to end, not mocks.
 *
 * Both ports are overridable (PLAYWRIGHT_PORT / PLAYWRIGHT_BACKEND_PORT) so two suites run
 * concurrently — or a CI job running alongside local dev — never collide on the same frontend
 * or backend (see docs/DECISIONS.md's test-isolation entry). Defaults are unchanged from
 * before, so a plain `npx playwright test` behaves exactly as it always did. */
const port = process.env.PLAYWRIGHT_PORT ?? '5197'
const backendPort = process.env.PLAYWRIGHT_BACKEND_PORT ?? '8000'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 5 * 60 * 1000, // real local-LLM ingestion/chat turns can take minutes, not ms
  expect: { timeout: 15_000 },
  fullyParallel: false, // every test shares the one backend's SQLite DB and Ollama instance
  // Adding the webkit project (SC-6) means two projects can now run concurrently even with
  // fullyParallel:false, which only serializes within a project — two simultaneous real
  // ingestions against the one shared backend crashed its embedder/reranker's Metal command
  // buffer on this machine. workers:1 keeps every project strictly sequential too.
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    // A dedicated, unusual port — not 5173/5174, which this machine may have other, unrelated
    // projects' dev servers already bound to (reuseExistingServer below only checks that
    // *something* answers the URL, not that it's this app).
    baseURL: `http://localhost:${port}`,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    // Scoped to the scroll regression spec only (SC-6 requires chromium + webkit there) —
    // every other spec stays chromium-only, so this doesn't double the full suite's runtime
    // or its real-LLM load on the one shared Ollama instance.
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
      testMatch: /workspace-scroll\.spec\.ts/,
    },
  ],
  webServer: {
    command: `npm run dev -- --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: true,
    timeout: 30_000,
    env: { VITE_BACKEND_PORT: backendPort },
  },
})
