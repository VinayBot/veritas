import { test, expect } from '@playwright/test'
import path from 'node:path'

/** One real walk through every tab, against a real backend — see tests/e2e/README.md.
 * Deliberately a single sequential test (not split per-page) since every later step depends
 * on the document uploaded in the first one; splitting it would mean re-ingesting per test. */
test('full workspace (incl. the embedded advisor panel) -> architecture (incl. per-node audit) -> graph -> evaluation (incl. safety suite) flow', async ({
  page,
  request,
}) => {
  const backendPort = process.env.PLAYWRIGHT_BACKEND_PORT ?? '8000'

  await test.step('backend is reachable', async () => {
    const health = await request
      .get(`http://localhost:${backendPort}/api/v1/health`)
      .catch(() => null)
    expect(
      health?.ok(),
      `Backend not reachable at :${backendPort} — start it first (make backend-dev or make dev)`,
    ).toBeTruthy()
  })

  const consoleErrors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    // GET /documents/{id}/advisor legitimately 404s ("no recommendation yet") while the
    // background enrichment phase hasn't produced one — the Workspace panel's Analyst
    // section already handles this gracefully (shows "No recommendation yet", not a crash),
    // but Chromium still logs the underlying failed network request to the console
    // regardless of app-level handling.
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

  await test.step('workspace panel shows the real advisor comparison and quality gauges', async () => {
    // No navigation — the Dashboard tab's content now lives in the Workspace panel itself
    // (see docs/DECISIONS.md TASK 3/4), already visible from the previous steps.
    const panel = page.getByTestId('document-intelligence-panel')
    await expect(panel).toBeVisible()
    await expect(panel.getByText('Analyst')).toBeVisible()

    // Graph/profile/advisor now run as a background enrichment phase *after* the document is
    // ready for chat (see docs/TROUBLESHOOTING.md), and the advisor tournament specifically
    // evaluates several candidate configs — each its own round of LLM calls — so racing its
    // indeterminate background completion time is flaky by construction. Instead, wait for
    // the advisor section to settle into one of its two real end states, then — if the
    // background run hasn't produced a recommendation yet — explicitly trigger it via the
    // real "Run advisor now" button, which maps to a synchronous POST /advisor/run with a
    // clear request/response contract instead of an open-ended wait.
    const suggestedMode = panel.getByText('Suggested RAG mode:')
    const runNowButton = panel.getByRole('button', { name: /run advisor now/i })
    await expect(suggestedMode.or(runNowButton)).toBeVisible({ timeout: 20_000 })
    if (await runNowButton.isVisible()) {
      await runNowButton.click()
    }
    await expect(suggestedMode).toBeVisible({ timeout: 180_000 })
    // getByText is substring + case-insensitive by default, so an unscoped 'Confidence' also
    // matches the chat bubble's "estimated: confidence NN%" badge — scope to the panel, where
    // the Gauge's own label is the only match.
    await expect(panel.getByText('Confidence')).toBeVisible()
  })

  await test.step('architecture tab connects to the live trace websocket', async () => {
    await page.getByRole('link', { name: 'Architecture' }).click()
    await expect(page).toHaveURL(/\/app\/architecture$/)
    // exact: true — a substring match on 'live' also matches "Upload & Deliver" (the Journey
    // view's checkpoint 1 label contains "deLIVEr"), so this needs to be unambiguous.
    await expect(page.getByText('live', { exact: true })).toBeVisible({ timeout: 15_000 })
    // Journey (the default view) shows 5 macro checkpoints, not all 10 individual stage
    // names — switch to Detailed for the full real node list this step is actually checking.
    await page.getByTestId('view-mode-detailed').click()
    await expect(page.getByText('Upload')).toBeVisible()
    await expect(page.getByText('Advisor')).toBeVisible()
  })

  await test.step('architecture node drawer shows the real guardrail audit entries for that node', async () => {
    // The chat step above already ran a real turn, so Guardian In's own trace event carries a
    // real trace_id with a real "allow" decision recorded against it (see docs/DECISIONS.md —
    // this replaced the standalone Guardrails tab's audit log once this per-node correlation
    // existed; getByRole('button', ...) rather than getByText since the chat lane's "Chat"
    // toggle also renders a plain-text source selector elsewhere on this same page).
    await page.getByRole('button', { name: 'Chat' }).click()
    await page.getByRole('button', { name: 'Guardian In' }).click()
    const auditSection = page.getByTestId('node-audit-entries')
    await expect(auditSection).toBeVisible()
    await expect(auditSection.getByText('allow')).toBeVisible({ timeout: 15_000 })
    // The drawer is a modal overlay — closing it is not just tidiness, an open one blocks
    // pointer events on every later nav link and silently hangs the next step's click.
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).not.toBeVisible()
  })

  await test.step('knowledge graph renders real extracted entities', async () => {
    await page.getByRole('link', { name: 'Knowledge Graph' }).click()
    await expect(page).toHaveURL(/\/app\/graph$/)
    await expect(page.locator('canvas')).toBeVisible({ timeout: 15_000 })
  })

  await test.step('evaluation tab is reachable, including the safety suite that replaced the Guardrails tab (benchmark/red-team runs not triggered — too slow for a smoke test)', async () => {
    await page.getByRole('link', { name: 'Evaluation' }).click()
    await expect(page).toHaveURL(/\/app\/evaluation$/)
    await expect(page.getByRole('button', { name: /generate dataset/i })).toBeVisible()
    const safetyCard = page.getByTestId('safety-redteam-card')
    await expect(safetyCard).toBeVisible()
    await expect(safetyCard.getByRole('button', { name: /run red-team suite/i })).toBeVisible()
  })

  await test.step('old Guardrails bookmark redirects instead of 404ing', async () => {
    await page.goto('/app/guardrails')
    await expect(page).toHaveURL(/\/app\/evaluation$/)
  })

  expect(consoleErrors, `Console errors during the flow:\n${consoleErrors.join('\n')}`).toEqual([])
})
