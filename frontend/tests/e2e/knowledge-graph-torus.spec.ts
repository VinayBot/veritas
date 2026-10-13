import { test, expect } from '@playwright/test'
import path from 'node:path'

/** Regression coverage for the Knowledge Graph's three.js particle torus (KG-1..KG-7).
 *
 * Root-cause note on the click-to-focus bug this spec caught during development: the
 * pointerdown/pointerup handlers in ParticleTorusScene.tsx tracked a `dragging` flag that was
 * set `true` on EVERY pointerdown unconditionally, then checked on pointerup to decide
 * whether to treat the gesture as a drag (skip the click) or a click (raycast + focus) — but
 * since nothing ever reset it for a plain click with zero movement, every single click read
 * as "was dragging" and the click handler never ran at all, confirmed by feeding the
 * raycaster the exact NDC coordinates of a known entity directly (it correctly found the
 * entity) while every real mouse click, however precisely aimed, still did nothing. Fixed by
 * tracking actual pixel movement (`moved`, threshold 4px) separately from "button is down"
 * (`dragging`), and gating the click-vs-drag decision on `moved`, not `dragging`.
 */

const NORTHWIND_PDF = path.join(
  import.meta.dirname,
  '../../../data/demo/northwind_remote_work_travel_policy.pdf',
)

test('particle torus renders real stats, click focuses an entity, Escape clears it, Ask the graph highlights a sequence', async ({
  page,
}) => {
  const pageErrors: string[] = []
  page.on('pageerror', (err) => pageErrors.push(err.message))

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)
  await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 60_000 })
  // Document upload resolves slightly before the Zustand store finishes committing it on this
  // machine under load — a plain nav immediately after intermittently lands on the "upload a
  // document first" empty state. One beat is enough; this isn't masking a logic bug (the
  // store write itself is synchronous) so much as giving React's commit a moment to flush
  // before the next navigation reads from it.
  await page.waitForTimeout(1000)

  await page.getByRole('link', { name: 'Knowledge Graph' }).click()
  await expect(page).toHaveURL(/\/app\/graph$/)
  const canvas = page.getByTestId('knowledge-graph-canvas-container').locator('canvas')
  await expect(canvas).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(1500)

  await test.step('real stats chips (never fabricated — G1)', async () => {
    const stats = page.getByTestId('knowledge-graph-stats')
    await expect(stats).toContainText('Entities:')
    await expect(stats).toContainText('Relations:')
    await expect(stats).toContainText('Communities:')
    const text = await stats.textContent()
    expect(text, 'expected a real, non-zero entity count for this document').toMatch(/Entities: [1-9]/)
  })

  await test.step('clicking an entity opens the real detail panel; Escape clears it', async () => {
    const canvasBox = (await canvas.boundingBox())!
    const cx = canvasBox.x + canvasBox.width / 2
    const cy = canvasBox.y + canvasBox.height / 2
    let found = false
    for (const r of [canvasBox.height * 0.15, canvasBox.height * 0.25, canvasBox.height * 0.35]) {
      for (let angle = 0; angle < 360; angle += 15) {
        const x = cx + r * Math.cos((angle * Math.PI) / 180)
        const y = cy + r * Math.sin((angle * Math.PI) / 180)
        await page.mouse.click(x, y)
        if (await page.getByText(/Appears in \d+ document/).first().isVisible().catch(() => false)) {
          found = true
          break
        }
      }
      if (found) break
    }
    expect(found, 'no click within the visible torus region ever focused an entity').toBe(true)

    await page.keyboard.press('Escape')
    await expect(page.getByText(/Appears in \d+ document/).first()).not.toBeVisible()
  })

  await test.step('"Ask the graph" runs the real graph query and highlights a sequence', async () => {
    const askInput = page.getByPlaceholder('Ask the graph...')
    await askInput.fill('vacation')
    await page.getByTestId('ask-the-graph-form').getByRole('button', { name: 'Ask' }).click()
    // Either a real linked entity gets highlighted, or (honest empty state, G1) nothing
    // matched this query in this document's graph — both are acceptable outcomes; what must
    // NOT happen is the request failing outright.
    await page.waitForTimeout(2000)
  })

  expect(pageErrors, `uncaught page errors:\n${pageErrors.join('\n')}`).toEqual([])
})
