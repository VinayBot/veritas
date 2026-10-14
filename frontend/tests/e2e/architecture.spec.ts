import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'

/** Real E2E for the Architecture tab against a real backend (see tests/e2e/README.md). */
const backendPort = process.env.PLAYWRIGHT_BACKEND_PORT ?? '8000'
const api = `http://localhost:${backendPort}/api/v1`

async function openArchitecture(page: Page) {
  await page.goto('/app/architecture')
  await expect(page.getByTestId('architecture-canvas')).toBeVisible({ timeout: 30_000 })
}

test('the diagram is drawn from the backend payload, in all three views', async ({ page, request }) => {
  const graph = await (await request.get(`${api}/architecture/graph`)).json()
  await openArchitecture(page)
  const canvas = page.getByTestId('architecture-canvas')

  // Overview: one node per stage that has modules.
  await expect(canvas).toHaveAttribute('data-view', 'overview')
  await expect(canvas).toHaveAttribute('data-node-count', String(graph.stages.length))

  // Detailed: every node and every edge the backend returned, no more and no fewer.
  await page.getByTestId('view-mode-detailed').click()
  await expect(canvas).toHaveAttribute('data-view', 'detailed')
  await expect(canvas).toHaveAttribute('data-node-count', String(graph.nodes.length))
  await expect(canvas).toHaveAttribute('data-edge-count', String(graph.edges.length))
  for (const node of graph.nodes.slice(0, 6)) {
    await expect(page.getByTestId(`arch-node-${node.id}`)).toBeAttached()
  }
  // Config values are visible on the nodes themselves in this view.
  await expect(page.getByTestId('arch-node-chunking')).toContainText('baseline')

  await page.getByTestId('view-mode-live').click()
  await expect(canvas).toHaveAttribute('data-node-count', String(graph.nodes.length))
  await expect(page.getByTestId('trace-dock')).toBeVisible()

  // No stale labels from the old hand-drawn diagram.
  for (const label of ['System Design', 'API Gateway', 'Shards', 'Replicas', 'Trace Event Bus']) {
    await expect(page.getByText(label, { exact: true })).toHaveCount(0)
  }
})

test('health strip shows one live pill per subsystem with its raw probe, and the self-check is diagnostic', async ({ page }) => {
  await openArchitecture(page)
  for (const id of ['ollama', 'chroma', 'bm25', 'graph_store', 'agent_graph', 'council', 'guardrails', 'trace_ws']) {
    await expect(page.getByTestId(`health-pill-${id}`)).toBeVisible({ timeout: 15_000 })
  }
  await expect(page.getByTestId('health-pill-ollama')).toHaveAttribute('data-status', 'healthy')

  await page.getByTestId('health-pill-agent_graph').click()
  const detail = page.getByTestId('health-detail-agent_graph')
  await expect(detail).toContainText('Compiled')
  await detail.getByText('Raw probe result').click()
  await expect(detail).toContainText('"nodes"')
  await page.keyboard.press('Escape')

  await page.getByTestId('run-self-check').click()
  const result = page.getByTestId('self-check-result')
  await expect(result).toBeVisible({ timeout: 120_000 })
  for (const stage of ['database', 'embed', 'dense_search', 'keyword_search', 'graph', 'generate', 'trace']) {
    await expect(page.getByTestId(`self-check-${stage}`)).toBeVisible()
  }
  await expect(page.getByTestId('self-check-embed')).toContainText('dimension')
  await expect(page.getByTestId('self-check-generate')).toContainText('token')
  await expect(result).toHaveAttribute('data-ok', 'true')
})

test('a node opens a drawer with purpose, config, real trace events and its source path — by keyboard too', async ({ page }) => {
  await openArchitecture(page)
  await page.getByTestId('view-mode-detailed').click()
  const node = page.getByTestId('arch-node-retrieval')
  const drawer = page.getByTestId('node-drawer')
  // The canvas is rebuilt when the view changes, so a key pressed in the first instant can
  // land on a node that is about to be replaced. Retried like a person would.
  await expect(async () => {
    await node.focus()
    await page.keyboard.press('Enter')
    await expect(drawer).toBeVisible({ timeout: 1500 })
  }).toPass({ timeout: 15_000 })
  await expect(drawer).toContainText('Retrieval')
  await expect(drawer.getByTestId('node-config')).toContainText('rrf k')
  await expect(drawer.getByTestId('node-source-path')).toHaveText('backend/app/retrieval')
  await expect(drawer.getByTestId('node-status-detail')).not.toBeEmpty()
  await page.keyboard.press('Escape')
  await expect(drawer).not.toBeVisible()
})

test('hovering a node dims everything that is not on its upstream or downstream path', async ({ page }) => {
  await openArchitecture(page)
  await page.getByTestId('view-mode-detailed').click()
  await page.getByTestId('arch-node-privacy').hover()
  await expect(page.getByTestId('arch-node-privacy')).toHaveCSS('opacity', '1')
  await expect(page.getByTestId('arch-node-ingestion')).toHaveCSS('opacity', '1') // upstream
  await expect(page.getByTestId('arch-node-chunking')).toHaveCSS('opacity', '1') // downstream
  // The LLM gateway is neither upstream nor downstream of the PII vault.
  await expect(page.getByTestId('arch-node-llm')).toHaveCSS('opacity', '0.25')
  await page.mouse.move(5, 5)
  await expect(page.getByTestId('arch-node-llm')).toHaveCSS('opacity', '1')
})

test('exports the real topology payload as JSON', async ({ page, request }) => {
  const graph = await (await request.get(`${api}/architecture/graph`)).json()
  await openArchitecture(page)
  await page.getByTestId('export-menu').click()
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId('export-json').click()])
  const stream = await download.createReadStream()
  let body = ''
  for await (const chunk of stream) body += chunk
  const exported = JSON.parse(body)
  expect(exported.nodes.map((n: { id: string }) => n.id).sort()).toEqual(graph.nodes.map((n: { id: string }) => n.id).sort())
  expect(exported.edges).toHaveLength(graph.edges.length)

  await page.getByTestId('export-menu').click()
  const [svg] = await Promise.all([page.waitForEvent('download'), page.getByTestId('export-svg').click()])
  expect(svg.suggestedFilename()).toMatch(/\.svg$/)
  await page.getByTestId('export-menu').click()
  const [png] = await Promise.all([page.waitForEvent('download'), page.getByTestId('export-png').click()])
  expect(png.suggestedFilename()).toMatch(/\.png$/)
})

async function uploadAndOpenLive(page: Page) {
  await page.goto('/app')
  // The sample PDF, not the tiny fixture: its background graph pass takes long enough that
  // the next stage (profile) starts while the Live view is open, which is the real hop the
  // tests below watch for. The tiny fixture now finishes before the view can be opened.
  await page
    .locator('input[type="file"]')
    .setInputFiles(path.join(import.meta.dirname, '../../../data/demo/northwind_remote_work_travel_policy.pdf'))
  // Do not wait for "ready": the point is to watch the pipeline while it is still running.
  await expect(page.getByTestId('document-switcher')).toContainText('northwind', { timeout: 30_000 })
  await page.getByRole('link', { name: 'Architecture' }).click()
  await page.getByTestId('view-mode-live').click()
}

test('pulses come only from real trace events: closing the socket stops them and flips the chip', async ({ page }) => {
  await uploadAndOpenLive(page)
  const chip = page.getByTestId('trace-status-chip')
  await expect(chip).toHaveAttribute('data-state', 'live', { timeout: 15_000 })
  // Real ingestion + enrichment events arrive and are listed.
  await expect(page.getByTestId('trace-events').getByRole('listitem').first()).toBeVisible({ timeout: 30_000 })
  // At least one pulse is drawn for a hop that really happened.
  const drawn = async () => Number(await page.getByTestId('pulses-drawn').textContent())
  await expect.poll(drawn, { timeout: 120_000 }).toBeGreaterThan(0)

  await page.getByTestId('toggle-trace-socket').click()
  await expect(chip).toHaveAttribute('data-state', 'disconnected')
  await expect(page.getByTestId('health-pill-trace_ws')).toHaveAttribute('data-status', 'down')
  await expect(page.locator('[data-packet]')).toHaveCount(0)
  await expect(page.locator('[data-activity="active"]')).toHaveCount(0)
  // Whatever the backend does next, with the socket closed nothing may move.
  const frozenAt = await drawn()
  await page.waitForTimeout(4000)
  await expect(page.locator('[data-packet]')).toHaveCount(0)
  expect(await drawn()).toBe(frozenAt)

  await page.getByTestId('toggle-trace-socket').click()
  await expect(chip).toHaveAttribute('data-state', 'live', { timeout: 15_000 })
})

test('with reduced motion the view is still fully usable and nothing animates', async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: 'reduce' })
  const page = await context.newPage()
  await uploadAndOpenLive(page)
  await expect(page.getByTestId('trace-status-chip')).toHaveAttribute('data-state', 'live', { timeout: 15_000 })
  await expect(page.getByTestId('trace-events').getByRole('listitem').first()).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(6000)
  await expect(page.locator('[data-packet]')).toHaveCount(0)
  await expect(page.getByTestId('pulses-drawn')).toHaveText('0')
  // The information survives: finished stages are marked on the nodes themselves.
  await expect(page.locator('[data-activity="done"]').first()).toBeAttached({ timeout: 60_000 })
  await context.close()
})
