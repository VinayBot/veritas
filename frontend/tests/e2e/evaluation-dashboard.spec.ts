import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'

/** EV-10: visual snapshots at 1440x900 and 1280x720, from a real document with a real
 * benchmark + advisor run (not a seeded fixture DB — none existed in this repo to seed from;
 * see the Phase 3 report's Assumptions). Also exercises the rest of EV-1..EV-9: real KPI
 * cards, the chart, the chunking-strategy table, the embedded Knowledge Graph panel, and the
 * mobile rail-becomes-bottom-bar breakpoint. */

const NORTHWIND_PDF = path.join(
  import.meta.dirname,
  '../../../data/demo/northwind_remote_work_travel_policy.pdf',
)
const SCREENS_DIR = path.join(import.meta.dirname, '../../../docs/screens')

test('Evaluation dashboard: real data end to end, responsive, visual snapshots', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)
  await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 60_000 })
  await page.waitForTimeout(1000)

  await page.getByRole('link', { name: 'Evaluation' }).click()
  await expect(page).toHaveURL(/\/app\/evaluation$/)

  await test.step('empty states are honest (G1) before any run exists', async () => {
    const kpis = page.getByTestId('eval-kpi-card')
    await expect(kpis).toHaveCount(4)
    await expect(kpis.first()).toContainText(/run a benchmark/i)
  })

  await test.step('left rail navigates to each section', async () => {
    for (const id of ['retrieval', 'chunking-advisor', 'guardrails', 'datasets', 'benchmarks', 'knowledge-graph']) {
      await page.getByTestId(`eval-rail-${id}`).click()
      await expect(page.locator(`#${id}`)).toBeInViewport({ timeout: 5_000 })
    }
    await page.getByTestId('eval-rail-overview').click()
  })

  // 10 minutes, not 3: the default benchmark run scores 6 real configs including two
  // (graph, agentic) that each run a full real multi-agent turn per eval item — the
  // pre-existing page's own copy already warned "this can take several minutes" before this
  // rewrite touched it, and measured real runs here took up to ~8 minutes.
  const REAL_RUN_TIMEOUT_MS = 600_000

  await test.step('real benchmark run populates KPIs, chart, and run health', async () => {
    await page.getByTestId('run-benchmark-button').click()
    await expect(page.getByText('No benchmark runs yet').first()).not.toBeVisible({
      timeout: REAL_RUN_TIMEOUT_MS,
    })
    await expect(page.getByTestId('eval-kpi-card').first()).not.toContainText(/run a benchmark/i)
  })

  await test.step('real advisor run populates the chunking-strategy table with real strategies', async () => {
    await page.getByRole('button', { name: /Run advisor/i }).click()
    await expect(page.getByText('No chunking comparison yet')).not.toBeVisible({
      timeout: REAL_RUN_TIMEOUT_MS,
    })
    const table = page.getByTestId('chunking-strategy-table')
    await expect(table).toContainText('recursive')
  })

  await test.step('the Knowledge Graph panel embeds a real, non-empty particle torus', async () => {
    await expect(page.locator('#knowledge-graph canvas')).toBeVisible({ timeout: 15_000 })
  })

  fs.mkdirSync(SCREENS_DIR, { recursive: true })

  await test.step('visual snapshot at 1440x900', async () => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.waitForTimeout(500)
    await page.screenshot({ path: path.join(SCREENS_DIR, 'evaluation-1440x900.png') })
  })

  await test.step('visual snapshot at 1280x720', async () => {
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.waitForTimeout(500)
    await page.screenshot({ path: path.join(SCREENS_DIR, 'evaluation-1280x720.png') })
  })

  await test.step('EV-9: below 768px the rail becomes a bottom bar, single column', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.waitForTimeout(500)
    const rail = page.getByTestId('evaluation-rail')
    const railBox = (await rail.boundingBox())!
    const kpiBox = (await page.getByTestId('eval-kpi-card').first().boundingBox())!
    expect(railBox.y, 'rail should sit at the bottom on mobile, not beside the content').toBeGreaterThan(kpiBox.y)
    await page.screenshot({ path: path.join(SCREENS_DIR, 'evaluation-mobile-390x844.png') })
  })
})
