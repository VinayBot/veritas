import { test, expect, type Page } from '@playwright/test'

/** Button by button: every control in the three tabs is pressed against the real backend and
 * local models, and its real effect is asserted. Slow by nature (it runs evaluations, a
 * red-team suite and graph builds); `app.spec.ts` is the quick pass. */

const API = 'http://localhost:8000/api/v1'

async function openSample(page: Page) {
  await page.goto('/app')
  await page.evaluate(() => localStorage.clear())
  await page.goto('/app')
  await page.getByTestId('load-sample-document').click()
  await expect(page.getByTestId('document-status')).toHaveText('ready', { timeout: 240_000 })
  const docs = await (await page.request.get(`${API}/documents?status=ready&limit=1`)).json()
  return docs.documents[0].id as string
}

async function ask(page: Page, question: string) {
  const before = await page.getByTestId('answer-meta').count()
  await page.getByLabel('Your question').fill(question)
  await page.getByTestId('send-question').click()
  await expect(page.getByTestId('answer-meta')).toHaveCount(before + 1, { timeout: 180_000 })
  return page.getByTestId('assistant-message').nth(before)
}

test('Workspace: starters, toggles, analysis panel, steps, clear chat, new document', async ({ page }) => {
  await openSample(page)

  // A starter question is a real question.
  await page.getByRole('button', { name: 'What is this document about?' }).click()
  await expect(page.getByTestId('answer-meta')).toHaveCount(1, { timeout: 180_000 })
  const first = page.getByTestId('assistant-message').first()
  await expect(first).not.toContainText('unable to generate')

  // Pipeline summary expands to the stepper and collapses again.
  await page.getByRole('button', { name: 'Show pipeline' }).click()
  await expect(page.getByRole('button', { name: 'Hide pipeline' })).toBeVisible()
  await page.getByRole('button', { name: 'Hide pipeline' }).click()
  await expect(page.getByTestId('ingestion-summary')).toBeVisible()

  const reveal = page.getByRole('button', { name: 'Reveal PII' })
  await reveal.click()
  await expect(reveal).toHaveAttribute('aria-pressed', 'true')
  await reveal.click()
  await expect(reveal).toHaveAttribute('aria-pressed', 'false')

  // The analysis of the answer: what was retrieved, the funnel, and where the time went.
  const panel = page.getByTestId('analysis-panel')
  await expect(panel).toBeVisible({ timeout: 120_000 })
  await expect(panel.getByTestId('retrieved-chunks')).toBeVisible()
  await expect(panel.getByTestId('retrieval-funnel')).toContainText(/\d/)
  await panel.getByRole('button', { name: /Trace timeline/ }).click()
  await expect(panel.getByTestId('trace-timeline')).toBeVisible()
  await expect(panel.getByTestId('answered-with')).toContainText(/\w/)

  // Agent steps expand under the answer.
  await first.getByRole('button', { name: /\d+ steps?/ }).click()
  await expect(first.locator('ol li').first()).toBeVisible()

  const second = await ask(page, 'How much is the home office stipend?')
  await expect(second).toContainText(/six hundred/i)
  // Selecting an older answer shows its analysis instead of the latest one.
  await first.getByTestId('inspect-answer').click()
  await expect(page.getByTestId('analyst-panel')).toContainText('Analysis of: What is this document about?', { timeout: 30_000 })

  await page.getByRole('button', { name: 'Clear chat' }).click()
  await expect(page.getByTestId('assistant-message')).toHaveCount(0)

  await page.getByTestId('new-document').click()
  await expect(page.getByTestId('workspace-empty')).toBeVisible()
})

test('Workspace: an answer in progress can be stopped', async ({ page }) => {
  await openSample(page)
  await page.getByTestId('deep-reasoning').click()
  await page.getByLabel('Your question').fill('Explain every rule in this policy about travel, expenses, equipment and remote work.')
  await page.getByTestId('send-question').click()
  await page.getByTestId('stop-answer').click({ timeout: 30_000 })
  // The composer comes back and the run is recorded as cancelled, not as an answer.
  await expect(page.getByTestId('send-question')).toBeVisible({ timeout: 30_000 })
  const runs = await (await page.request.get(`${API}/analytics/overview?days=1`)).json()
  expect(runs.reliability.cancelled).toBeGreaterThan(0)
  await expect(page.getByTestId('answer-meta')).toHaveCount(0)
})

test('Workspace: switching the answer model changes which model answers', async ({ page }) => {
  await openSample(page)
  const before = (await (await page.request.get(`${API}/models/local`)).json()).selection.generator as string
  const other = before.endsWith('llama3.2:3b') ? 'gemma2:2b' : 'llama3.2:3b'
  try {
    await page.getByTestId('model-picker').click()
    await page.getByTestId(`model-option-${other}`).click()
    await expect(page.getByTestId('model-picker')).toContainText(other, { timeout: 60_000 })
    const answer = await ask(page, 'Who approves trips over five thousand dollars?')
    await expect(answer.getByTestId('answer-meta')).toContainText(other)

    // The full settings dialog opens from the picker and lists every role.
    await page.getByTestId('model-picker').click()
    await page.getByTestId('open-model-settings').click()
    const dialog = page.getByTestId('settings-dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText(/judge/i)
    await expect(dialog).toContainText(/embedding/i)
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
  } finally {
    await page.request.put(`${API}/models/selection`, { data: { generator: before } })
  }
})

test('Workspace: a strategy that needs an index offers to build it, then answers', async ({ page }) => {
  await openSample(page)
  await page.getByTestId('strategy-picker').click()
  const naive = page.getByTestId('strategy-option-naive')
  await expect(naive).toHaveAttribute('data-available', 'false')
  await page.getByTestId('strategy-build-naive').click()
  await expect(naive).toHaveAttribute('data-available', 'true', { timeout: 180_000 })
  await naive.getByRole('button').first().click()
  const answer = await ask(page, 'How many days per week may employees work remotely?')
  await expect(answer.getByTestId('answer-meta')).toContainText('Answered with: Naive')
  await expect(answer).toContainText(/three/i)
})

test('Workspace: the recommendation explains itself and can be re-measured', async ({ page }) => {
  // Graph reading and the strategy measurement are real model work in the background.
  test.setTimeout(10 * 60_000)
  const id = await openSample(page)
  const card = page.getByTestId('recommendation-card')
  await expect(card).toBeVisible({ timeout: 60_000 })
  await expect(card).toHaveAttribute('data-basis', 'measured', { timeout: 420_000 })
  await card.getByRole('button', { name: 'How was this decided?' }).click()
  await expect(card.getByTestId('recommendation-details')).toContainText('Rules checked')
  await expect(card.getByTestId('recommendation-details')).toContainText(/Measured on \d+ question/)

  // Re-measure runs again and keeps the highest scorer in use.
  await card.getByTestId('measure-now').click()
  await expect(card.getByTestId('measuring')).toBeVisible({ timeout: 30_000 })
  await expect(card.getByTestId('measuring')).toBeHidden({ timeout: 300_000 })
  const rec = await (await page.request.get(`${API}/documents/${id}/recommendation`)).json()
  expect(rec.recommended).toBe(rec.measured.ranking[0].strategy)
  await expect(card.getByTestId('recommended-score')).toHaveText(`score ${rec.measured.ranking[0].score.toFixed(2)}`)

  // Picking another strategy for this document from the comparison sticks.
  const second = rec.measured.ranking[1]
  await page.getByTestId('strategy-picker').click()
  await page.getByRole('button', { name: `Use ${second.display_name} for this document` }).click()
  await expect.poll(async () => (await (await page.request.get(`${API}/documents/${id}`)).json()).preferred_strategy).toBe(second.strategy)
  await expect(page.getByTestId('strategy-picker')).toContainText(second.display_name, { timeout: 15_000 })
})

test('Header: document switcher (filter, select, delete), theme toggle, command palette', async ({ page }) => {
  const id = await openSample(page)
  await ask(page, 'How much is the home office stipend?')

  await page.getByTestId('document-switcher').click()
  await page.getByLabel('Filter documents').fill('northwind')
  await expect(page.getByTestId(`document-option-${id}`)).toBeVisible()
  await page.getByLabel('Filter documents').fill('zzz-no-such-file')
  await expect(page.getByTestId(`document-option-${id}`)).toHaveCount(0)
  await page.getByLabel('Filter documents').fill('')

  // Deleting the active document removes it from the backend and returns to the empty state.
  await page.locator('li', { has: page.getByTestId(`document-option-${id}`) }).getByRole('button', { name: /^Delete / }).click()
  await page.getByTestId('confirm-accept').click()
  await expect.poll(async () => (await page.request.get(`${API}/documents/${id}`)).status(), { timeout: 30_000 }).toBe(404)
  // The list closes by itself when the working document is deleted.
  await expect(page.getByLabel('Filter documents')).toBeHidden({ timeout: 15_000 })
  await expect(page.getByTestId('workspace-empty')).toBeVisible({ timeout: 30_000 })

  const html = page.locator('html')
  await page.getByRole('switch', { name: 'Switch to light theme' }).click()
  await expect(html).toHaveClass(/light/)
  await page.getByRole('switch', { name: 'Switch to dark theme' }).click()
  await expect(html).not.toHaveClass(/light/)

  await page.getByRole('button', { name: 'Open the command palette' }).click()
  await page.keyboard.type('Evaluation: Safety')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/view=safety/)
})

test('Architecture: self-check, exports, live trace controls', async ({ page }) => {
  await openSample(page)
  await ask(page, 'How much is the home office stipend?')
  // In-app navigation: the chat session being traced belongs to this page load.
  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'Architecture' }).click()
  await expect(page.getByTestId('architecture-canvas')).toBeVisible()

  await page.getByTestId('run-self-check').click()
  const result = page.getByTestId('self-check-result')
  await expect(result).toBeVisible({ timeout: 120_000 })
  for (const stage of ['database', 'embed', 'dense_search', 'keyword_search', 'generate']) {
    await expect(page.getByTestId(`self-check-${stage}`)).toBeVisible()
  }

  for (const kind of ['svg', 'png'] as const) {
    await page.getByTestId('export-menu').click()
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId(`export-${kind}`).click()])
    expect(download.suggestedFilename()).toMatch(new RegExp(`\\.${kind}$`))
  }

  await page.getByTestId('view-mode-live').click()
  const dock = page.getByTestId('trace-dock')
  await expect(dock).toBeVisible()
  // The chat turn just asked is in the event list, with real stage names.
  await expect(dock.getByTestId('trace-events')).toContainText(/synthesizer/, { timeout: 30_000 })
  await dock.getByTestId('replay-trace').click()
  await expect(dock.getByTestId('trace-status-chip')).toContainText(/replay/i)
  await dock.getByTestId('toggle-trace-socket').click()
  await expect(dock.getByTestId('trace-status-chip')).toContainText(/disconnected|paused|off|idle/i, { timeout: 15_000 })
  await page.getByTestId('arch-fit').click()
})

test('Evaluation: usage window, table fallbacks, a run with per-question drill-down', async ({ page }) => {
  await openSample(page)
  await ask(page, 'How much is the home office stipend?')
  await page.goto('/app/evaluation')

  await page.getByRole('radio', { name: '7 days' }).click()
  await expect(page.getByRole('radio', { name: '7 days' })).toHaveAttribute('aria-checked', 'true')
  const week = await (await page.request.get(`${API}/analytics/overview?days=7`)).json()
  await expect(page.getByTestId('usage-kpi-questions')).toContainText(String(week.queries.in_window), { timeout: 30_000 })

  // Every chart has the same numbers as a table.
  const volume = page.getByTestId('usage-volume')
  await volume.getByRole('button', { name: 'View as table' }).click()
  await expect(volume.getByRole('table')).toBeVisible()
  await volume.getByRole('button', { name: 'View as chart' }).click()

  await page.getByTestId('run-eval-button').click()
  await page.getByTestId('confirm-accept').click()
  await expect(page.getByTestId('eval-strategy-table')).toBeVisible({ timeout: 300_000 })
  const table = page.getByTestId('eval-strategy-table')
  await table.locator('tbody tr').first().click()
  const samples = page.getByTestId('eval-samples')
  await expect(samples).toBeVisible()
  // A real question from the eval set, with its measured latency.
  await expect(samples.locator('tbody tr').first()).toContainText(/[A-Za-z]{4,}.*\d(ms|s)/s, { timeout: 30_000 })
  await expect(page.getByTestId('eval-gates')).toContainText('Faithfulness')
  // Sorting a column re-orders without losing rows.
  const rows = await table.locator('tbody tr').count()
  await table.getByRole('button', { name: /p50/ }).first().click()
  await expect(table.locator('tbody tr')).toHaveCount(rows)
})

test('Evaluation: knowledge graph filter and rebuild', async ({ page }) => {
  const id = await openSample(page)
  await expect
    .poll(async () => (await (await page.request.get(`${API}/documents/${id}`)).json()).enrichment_status, { timeout: 300_000, intervals: [2000] })
    .toBe('done')
  await page.goto('/app/evaluation?view=graph')
  await expect(page.getByTestId('knowledge-graph-stats')).toBeVisible({ timeout: 30_000 })

  await page.getByLabel('Filter the graph by entity').fill('zzzz-not-an-entity')
  await page.getByRole('button', { name: 'Apply filter' }).click()
  await expect(page.getByText(/Nothing in the graph matches/)).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Clear filter' }).click()
  await expect(page.getByTestId('knowledge-graph-stats')).toBeVisible({ timeout: 30_000 })

  await page.getByTestId('rebuild-graph').click()
  await expect(page.getByTestId('graph-build-progress')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('graph-build-progress')).toBeHidden({ timeout: 240_000 })
  const stats = await (await page.request.get(`${API}/graph/stats?document_id=${id}`)).json()
  expect(stats.entities).toBeGreaterThan(0)
  await expect(page.getByTestId('graph-kpi-entities')).toContainText(String(stats.entities), { timeout: 30_000 })
})

test('Evaluation: safety filters and the red-team suite', async ({ page }) => {
  await openSample(page)
  await ask(page, 'How much is the home office stipend?')
  await page.goto('/app/evaluation?view=safety')

  const log = page.getByTestId('audit-log')
  await log.getByRole('radio', { name: 'Input' }).click()
  await expect(log.locator('tbody tr').first()).toContainText('input', { timeout: 30_000 })
  await log.getByRole('radio', { name: 'All' }).click()
  await log.getByRole('button', { name: 'Tripped only' }).click()
  await expect(log.getByRole('button', { name: 'Tripped only' })).toHaveAttribute('aria-pressed', 'true')
  // No row's decision is "allow" (the word can still occur inside an excerpt).
  await expect(log.locator('tbody tr td:nth-child(4)').filter({ hasText: /^allow$/ })).toHaveCount(0)

  await page.getByTestId('run-redteam-button').click()
  await page.getByTestId('confirm-accept').click()
  await expect(page.getByTestId('redteam-results')).toBeVisible({ timeout: 420_000 })
  await expect(page.getByTestId('guardrails-kpi-redteam')).toContainText(/\d+\/\d+ attacks/)
  await expect(page.getByTestId('redteam-panel')).toContainText(/block rate \d/)
})
