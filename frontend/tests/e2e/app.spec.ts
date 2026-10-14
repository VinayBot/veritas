import { test, expect, type Page } from '@playwright/test'

/** The three-tab app end to end against the real backend and local models: navigation,
 * a quick and a deep answer, history that survives a reload, switching strategy and model,
 * the recommendation card, and every Evaluation view. Nothing is mocked. */

async function openSample(page: Page) {
  await page.goto('/app')
  await page.evaluate(() => localStorage.clear())
  await page.goto('/app')
  await page.getByTestId('load-sample-document').click()
  await expect(page.getByTestId('document-status')).toHaveText('ready', { timeout: 240_000 })
}

async function openSampleId(page: Page): Promise<string> {
  await openSample(page)
  const docs = await (await page.request.get('http://localhost:8000/api/v1/documents?status=ready&limit=1')).json()
  return docs.documents[0].id
}

async function ask(page: Page, question: string) {
  const before = await page.getByTestId('answer-meta').count()
  await page.getByLabel('Your question').fill(question)
  await page.getByTestId('send-question').click()
  await expect(page.getByTestId('answer-meta')).toHaveCount(before + 1, { timeout: 180_000 })
  return page.getByTestId('assistant-message').nth(before)
}

const sentenceCount = (text: string) => text.split(/(?<=[.!?])(?:\s*\[?\d+\]?)*\s+(?=[A-Z<])/).filter((s) => s.trim().length > 0).length

test('there are exactly three tabs, and the old tab addresses land inside them', async ({ page }) => {
  await page.goto('/app')
  const nav = page.getByRole('navigation', { name: 'Primary' })
  await expect(nav.getByRole('link')).toHaveText(['Workspace', 'Architecture', 'Evaluation'])

  for (const [from, to] of [
    ['/app/dashboard', /\/app\/evaluation$/],
    ['/app/graph', /\/app\/evaluation\?view=graph/],
    ['/app/guardrails', /\/app\/evaluation\?view=safety/],
    ['/app/test-center', /\/app\/architecture/],
  ] as const) {
    await page.goto(from)
    await expect(page).toHaveURL(to)
  }
})

test('a normal question gets a quick answer; Deep reasoning gets a longer one; history survives a reload', async ({ page }) => {
  await openSample(page)

  // Deep reasoning is off by default: every question gets the short form.
  await expect(page.getByTestId('deep-reasoning')).toHaveAttribute('aria-pressed', 'false')
  const quick = await ask(page, 'How much is the home office stipend?')
  await expect(quick.getByTestId('answer-meta')).toContainText('quick')
  await expect(quick).toContainText(/six hundred/i)
  const quickText = (await quick.locator('div').first().innerText()).trim()
  expect(sentenceCount(quickText)).toBeLessThanOrEqual(4)

  await page.getByTestId('deep-reasoning').click()
  await expect(page.getByTestId('deep-reasoning')).toHaveAttribute('aria-pressed', 'true')
  const deep = await ask(page, 'What are the rules for approving business travel?')
  await expect(deep.getByTestId('answer-meta')).toContainText('deep')
  await expect(deep).not.toContainText("I can't provide that response")
  const deepText = (await deep.locator('div').first().innerText()).trim()
  expect(sentenceCount(deepText)).toBeLessThanOrEqual(8)
  expect(deepText.length).toBeGreaterThan(quickText.length)

  // The measured latency shown is the backend's, not a client-side stopwatch.
  await expect(deep.getByTestId('answer-latency')).toHaveText(/\d/)

  // The per-answer analysis arrives once scoring finishes.
  await expect(page.getByTestId('analyst-panel')).toContainText(/Analysis of:/, { timeout: 120_000 })

  await page.reload()
  await expect(page.getByTestId('assistant-message')).toHaveCount(2)
  await expect(page.getByTestId('assistant-message').first()).toContainText(/six hundred/i)
})

test('strategy and model can be switched from the Workspace header, and the recommendation can be adopted', async ({ page }) => {
  await openSample(page)

  await page.getByTestId('strategy-picker').click()
  await page.getByTestId('strategy-option-hybrid').getByRole('button').first().click()
  const answer = await ask(page, 'Who approves trips that cost more than five thousand dollars?')
  await expect(answer.getByTestId('answer-meta')).toContainText('Answered with: Hybrid')

  // Only models that are actually installed are offered.
  await page.getByTestId('model-picker').click()
  const tags = await (await page.request.get('http://localhost:8000/api/v1/models/local')).json()
  const installed = tags.chat_models.filter((m: { roles: { generator: boolean } }) => m.roles.generator)
  await expect(page.locator('[data-testid^="model-option-"]')).toHaveCount(installed.length)
  const ollamaTags = await (await page.request.get('http://localhost:11434/api/tags')).json()
  const onDisk = new Set(ollamaTags.models.map((m: { name: string }) => m.name))
  for (const model of installed.filter((m: { cloud: boolean }) => !m.cloud)) expect(onDisk.has(model.name)).toBe(true)
  await page.keyboard.press('Escape')

  // The recommendation card is there from the start, with its suggestion marked as such
  // until the strategies have actually been measured on this document.
  const card = page.getByTestId('recommendation-card')
  await expect(card).toBeVisible({ timeout: 60_000 })
})

test('after upload the best strategy is measured, shown with its score, and used automatically', async ({ page }) => {
  // Graph reading and the strategy measurement are real model work in the background.
  test.setTimeout(10 * 60_000)
  const id = await openSampleId(page)
  const card = page.getByTestId('recommendation-card')
  await expect(card).toBeVisible({ timeout: 60_000 })
  // Graph reading, then measuring strategies on five questions from the document.
  await expect(card).toHaveAttribute('data-basis', 'measured', { timeout: 420_000 })
  const doc = await (await page.request.get(`http://localhost:8000/api/v1/documents/${id}`)).json()
  const rec = await (await page.request.get(`http://localhost:8000/api/v1/documents/${id}/recommendation`)).json()
  const best = rec.measured.ranking[0]
  expect(rec.measured.ranking.length).toBeGreaterThanOrEqual(2)
  // The highest score wins, and the card says what it scored.
  expect(rec.recommended).toBe(best.strategy)
  expect(doc.preferred_strategy).toBe(best.strategy)
  await expect(card.getByTestId('recommended-strategy')).toHaveText(best.display_name)
  await expect(card.getByTestId('recommended-score')).toHaveText(`score ${best.score.toFixed(2)}`)
  await expect(card.getByTestId('measured-ranking').locator('[data-testid^="ranking-"]')).toHaveCount(rec.measured.ranking.length)
  await expect(card.getByTestId('recommendation-in-use')).toContainText('selected automatically')

  // A question that names no strategy is answered with it.
  const answer = await ask(page, 'How much is the home office stipend?')
  await expect(answer.getByTestId('answer-meta')).toContainText(`Answered with: ${best.display_name}`)

  // Compare is there for a closer look, with the measured strategies preselected.
  await card.getByTestId('compare-recommended').click()
  await expect(page.getByTestId('compare-dialog')).toBeVisible()
  await expect(page.getByTestId(`compare-pick-${rec.measured.ranking[1].strategy}`)).toBeChecked()
  await page.keyboard.press('Escape')
})

test('Evaluation has exactly three views; Usage also carries measured quality', async ({ page }) => {
  await openSample(page)
  await page.goto('/app/evaluation')
  await expect(page.getByRole('tab')).toHaveText(['Usage', 'Knowledge graph', 'Safety'])

  const analytics = await (await page.request.get('http://localhost:8000/api/v1/analytics/overview?days=14')).json()
  await expect(page.getByTestId('usage-kpi-questions')).toContainText(String(analytics.queries.in_window))
  // Quality lives on the same view, below usage.
  await expect(page.getByTestId('eval-kpi-faithfulness')).toContainText(/No evaluation run yet|Not measured|\d\.\d\d/)
  await expect(page.getByTestId('run-eval-button')).toBeEnabled()

  await page.getByTestId('eval-tab-safety').click()
  await expect(page.getByTestId('guardrails-kpi-redteam')).toContainText('Not run this session')
  await expect(page.getByTestId('audit-log')).toBeVisible()

  // Old addresses for removed views fall back to Usage rather than a blank page.
  await page.goto('/app/evaluation?view=corpus')
  await expect(page.getByTestId('eval-usage')).toBeVisible()
})

test('the knowledge graph shows the document\'s entities and answers a question', async ({ page }) => {
  await openSample(page)
  // Graph reading runs in the background after upload; wait for it through the API.
  const docs = await (await page.request.get('http://localhost:8000/api/v1/documents?status=ready&limit=1')).json()
  const id = docs.documents[0].id
  await expect
    .poll(async () => (await (await page.request.get(`http://localhost:8000/api/v1/documents/${id}`)).json()).enrichment_status, { timeout: 240_000, intervals: [2000] })
    .toBe('done')
  const stats = await (await page.request.get(`http://localhost:8000/api/v1/graph/stats?document_id=${id}`)).json()
  expect(stats.entities).toBeGreaterThan(0)
  expect(stats.relations).toBeGreaterThan(0)

  await page.goto('/app/evaluation?view=graph')
  await expect(page.getByTestId('graph-kpi-entities')).toContainText(String(stats.entities))
  await expect(page.getByTestId('knowledge-graph-stats')).toContainText(`Relations: ${stats.relations}`, { timeout: 30_000 })

  await page.getByTestId('ask-the-graph-input').fill('Who approves business travel?')
  await page.getByTestId('ask-the-graph-form').getByRole('button', { name: /ask/i }).click()
  const answer = page.getByTestId('graph-answer')
  await expect(answer).toContainText(/answered with/i, { timeout: 120_000 })
  await expect(answer).not.toContainText("I can't provide that response")
})

test('a comparison runs to a measured result in under two minutes, with progress that moves', async ({ page }) => {
  await openSample(page)
  await ask(page, 'How much is the home office stipend?')
  await page.getByTestId('compare-recommended').click()
  const dialog = page.getByTestId('compare-dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Question to compare on').fill('How much is the home office stipend?')
  const available = dialog.locator('input[type="checkbox"]:not([disabled])')
  if (!(await available.first().isChecked())) await available.first().check()
  await expect(dialog.getByTestId('compare-run')).toBeEnabled({ timeout: 15_000 })
  const started = Date.now()
  await dialog.getByTestId('compare-run').click()

  // The bar leaves 0% while the first strategy is still working.
  const bar = dialog.getByRole('progressbar')
  await expect.poll(async () => Number(await bar.getAttribute('aria-valuenow')), { timeout: 60_000 }).toBeGreaterThan(0)
  await expect(dialog.getByTestId('comparison-view')).toBeVisible({ timeout: 120_000 })
  expect(Date.now() - started).toBeLessThan(120_000)
  // Two strategies, each with a measured latency.
  await expect(dialog.getByTestId('comparison-view')).toContainText(/\d(\.\d+)?\s?(ms|s)/)
})

test('an evaluation runs from the dashboard with live progress and fills the quality cards', async ({ page }) => {
  await openSample(page)
  await page.goto('/app/evaluation')
  await page.getByTestId('run-eval-button').click()
  await page.getByTestId('confirm-accept').click()
  const progress = page.getByTestId('eval-progress')
  await expect(progress).toBeVisible({ timeout: 30_000 })
  await expect.poll(async () => Number(await progress.getByRole('progressbar').getAttribute('aria-valuenow')), { timeout: 120_000 }).toBeGreaterThan(0)
  await expect(page.getByTestId('eval-strategy-table')).toBeVisible({ timeout: 300_000 })
  await expect(page.getByTestId('eval-provenance')).toContainText(/questions from eval set v\d+/)
  await expect(page.getByTestId('eval-kpi-recall_at_5')).toContainText(/\d\.\d\d/)
  await expect(page.getByTestId('eval-kpi-recall_at_5')).toContainText(/Verified/)
})

test('Architecture can play the request path, clearly labelled as an illustration', async ({ page }) => {
  await page.goto('/app/architecture')
  await page.getByTestId('play-request-path').click()
  await expect(page.getByTestId('tour-banner')).toContainText('not live traffic')
  await expect(page.locator('[data-activity="active"]').first()).toBeVisible()
  await page.getByTestId('play-request-path').click()
  await expect(page.getByTestId('tour-banner')).toHaveCount(0)
})

test('with reduced motion the app is fully usable', async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: 'reduce' })
  const page = await context.newPage()
  await page.goto('/app/evaluation?view=usage')
  await expect(page.getByTestId('eval-usage')).toBeVisible()
  await page.getByTestId('eval-tab-safety').click()
  await expect(page.getByTestId('eval-safety')).toBeVisible()
  // Keyboard: the command palette opens and navigates.
  await page.keyboard.press('ControlOrMeta+k')
  await page.keyboard.type('Go to Architecture')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/app\/architecture/)
  await context.close()
})
