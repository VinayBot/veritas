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
    ['/app/dashboard', /\/app\/evaluation\?view=usage/],
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

  const card = page.getByTestId('recommendation-card')
  await expect(card).toBeVisible({ timeout: 60_000 })
  await expect(card.getByTestId('recommendation-reasons').locator('li').first()).toContainText(/\d/)
  if (await card.getByTestId('use-recommended').isVisible()) {
    await card.getByTestId('use-recommended').click()
  }
  await expect(card.getByTestId('recommendation-in-use')).toBeVisible({ timeout: 120_000 })
  // After adopting it, the card offers to measure what changed rather than claiming a gain.
  await expect(card.getByTestId('improvement-panel')).toBeVisible()
})

test('every Evaluation view renders real data or an honest empty state', async ({ page }) => {
  await openSample(page)
  await page.goto('/app/evaluation')

  await expect(page.getByTestId('eval-kpi-faithfulness')).toContainText(/No evaluation run yet|Not measured|\d\.\d\d/)
  await expect(page.getByTestId('run-eval-button')).toBeEnabled()

  await page.getByTestId('eval-tab-usage').click()
  const analytics = await (await page.request.get('http://localhost:8000/api/v1/analytics/overview?days=14')).json()
  await expect(page.getByTestId('usage-kpi-questions')).toContainText(String(analytics.queries.in_window))

  await page.getByTestId('eval-tab-graph').click()
  await expect(page.getByTestId('graph-kpi-entities')).toBeVisible()

  await page.getByTestId('eval-tab-safety').click()
  await expect(page.getByTestId('guardrails-kpi-redteam')).toContainText('Not run this session')
  await expect(page.getByTestId('audit-log')).toBeVisible()

  await page.getByTestId('eval-tab-corpus').click()
  await expect(page.getByTestId('corpus-table')).toContainText('northwind_remote_work_travel_policy.pdf')
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
