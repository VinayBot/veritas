import { test, expect } from '@playwright/test'
import path from 'node:path'

/** One real walk through every tab, against a real backend — see tests/e2e/README.md.
 * Deliberately a single sequential test (not split per-page) since every later step depends
 * on the document uploaded in the first one; splitting it would mean re-ingesting per test. */
test('full workspace -> dashboard -> architecture -> graph -> guardrails -> evaluation flow', async ({
  page,
  request,
}) => {
  await test.step('backend is reachable', async () => {
    const health = await request.get('http://localhost:8000/api/v1/health').catch(() => null)
    expect(
      health?.ok(),
      'Backend not reachable at :8000 — start it first (make backend-dev or make dev)',
    ).toBeTruthy()
  })

  const consoleErrors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    // GET /documents/{id}/advisor legitimately 404s ("no recommendation yet") while the
    // background enrichment phase hasn't produced one — DashboardPage already handles this
    // gracefully (shows "No recommendation yet", not a crash), but Chromium still logs the
    // underlying failed network request to the console regardless of app-level handling.
    // This specific race window didn't exist before ingestion became async (see
    // docs/TROUBLESHOOTING.md) — real synchronous completion meant a recommendation always
    // already existed by the time Dashboard could ask for it.
    if (/\/documents\/[^/]+\/advisor$/.test(msg.location().url ?? '')) return
    consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`))

  await test.step('landing page renders', async () => {
    await page.goto('/')
    await expect(page).toHaveTitle('Veritas')
    await expect(page.getByRole('heading', { name: /adaptive rag platform/i })).toBeVisible()
  })

  await test.step('navigate into the workspace', async () => {
    await page.getByRole('link', { name: /open workspace/i }).click()
    await expect(page).toHaveURL(/\/app$/)
    await expect(page.getByText(/drop a document here/i)).toBeVisible()
  })

  await test.step('upload a real document and watch it ingest', async () => {
    await page.locator('input[type="file"]').setInputFiles(path.join(import.meta.dirname, 'fixture.md'))
    // Ingestion runs as a detached background job (app/ingestion/service.py) — the frontend
    // polls GET /documents/{id} every 2s until status lands on "ready" (see
    // docs/TROUBLESHOOTING.md); graph/profile/advisor keep running afterward as enrichment.
    await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 240_000 })
    await expect(page.getByText(/chunks \(/)).toBeVisible()
  })

  await test.step('chat with the document and get a real, cited, scored answer', async () => {
    const input = page.getByPlaceholder(/ask a question/i)
    await input.fill('How many vacation days do employees accrue per month?')
    await input.press('Enter')
    await expect(page.getByText(/estimated: confidence/i)).toBeVisible({ timeout: 120_000 })
  })

  await test.step('dashboard shows the real advisor comparison and quality gauges', async () => {
    await page.getByRole('link', { name: 'Dashboard' }).click()
    await expect(page).toHaveURL(/\/app\/dashboard$/)
    await expect(page.getByText('Model & Chunking Advisor')).toBeVisible()

    // Graph/profile/advisor now run as a background enrichment phase *after* the document is
    // ready for chat (see docs/TROUBLESHOOTING.md), and the advisor tournament specifically
    // evaluates several candidate configs — each its own round of LLM calls — so racing its
    // indeterminate background completion time is flaky by construction. Instead, wait for
    // the advisor section to settle into one of its two real end states, then — if the
    // background run hasn't produced a recommendation yet — explicitly trigger it via the
    // real "Run advisor now" button, which maps to a synchronous POST /advisor/run with a
    // clear request/response contract instead of an open-ended wait.
    const suggestedMode = page.getByText('Suggested RAG mode:')
    const runNowButton = page.getByRole('button', { name: /run advisor now/i })
    await expect(suggestedMode.or(runNowButton)).toBeVisible({ timeout: 20_000 })
    if (await runNowButton.isVisible()) {
      await runNowButton.click()
    }
    await expect(suggestedMode).toBeVisible({ timeout: 180_000 })
    await expect(page.getByText('Confidence')).toBeVisible()
  })

  await test.step('architecture tab connects to the live trace websocket', async () => {
    await page.getByRole('link', { name: 'Architecture' }).click()
    await expect(page).toHaveURL(/\/app\/architecture$/)
    await expect(page.getByText('live')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('Upload')).toBeVisible()
    await expect(page.getByText('Advisor')).toBeVisible()
  })

  await test.step('knowledge graph renders real extracted entities', async () => {
    await page.getByRole('link', { name: 'Knowledge Graph' }).click()
    await expect(page).toHaveURL(/\/app\/graph$/)
    await expect(page.locator('canvas')).toBeVisible({ timeout: 15_000 })
  })

  await test.step('guardrails tab shows the real audit log', async () => {
    await page.getByRole('link', { name: 'Guardrails' }).click()
    await expect(page).toHaveURL(/\/app\/guardrails$/)
    await expect(page.getByText('input_checks').first()).toBeVisible({ timeout: 15_000 })
  })

  await test.step('evaluation tab is reachable (benchmark run not triggered — too slow for a smoke test)', async () => {
    await page.getByRole('link', { name: 'Evaluation' }).click()
    await expect(page).toHaveURL(/\/app\/evaluation$/)
    await expect(page.getByRole('button', { name: /generate dataset/i })).toBeVisible()
  })

  expect(consoleErrors, `Console errors during the flow:\n${consoleErrors.join('\n')}`).toEqual([])
})
