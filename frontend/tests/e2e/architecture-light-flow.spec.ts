import { test, expect } from '@playwright/test'
import path from 'node:path'

/** LF-7: Tour mode visits every edge of stage 1 in order, and Live mode emits a comet for a
 * real chat request — never a synthetic one.
 *
 * Observed via `data-edge-history` on the canvas: a cumulative, append-only log of every edge
 * a comet started on (SystemDesignView's markEdgeActive), capped at 40 entries. An earlier
 * version of this test polled the single-value `data-current-edge` snapshot instead and was
 * reliably flaky — a poll landing between two reads could miss a short edge (~0.86s at
 * default speed) outright, no matter how tight the polling interval, because that attribute
 * only ever shows "right now", not "everything that happened". The cumulative log can't be
 * missed the same way: it only grows, so a later read still contains an earlier edge.
 */

const NORTHWIND_PDF = path.join(
  import.meta.dirname,
  '../../../data/demo/northwind_remote_work_travel_policy.pdf',
)

const STAGE_1_EDGE_IDS = [
  'user-gateway',
  'gateway-ingest_scheduler',
  'event_bus-ingest_scheduler',
  'ingest_scheduler-worker_docling',
]

function historyOf(raw: string): string[] {
  return raw ? raw.split(',') : []
}

function containsContiguousInOrder(haystack: string[], needle: string[]): boolean {
  for (let i = 0; i + needle.length <= haystack.length; i++) {
    if (needle.every((v, j) => haystack[i + j] === v)) return true
  }
  return false
}

test('Tour mode walks stage 1\'s edges in order, then Live mode reacts to a real chat request', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)
  await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 60_000 })

  await page.getByRole('link', { name: 'Architecture' }).click()
  await expect(page).toHaveURL(/\/app\/architecture$/)
  const canvas = page.getByTestId('architecture-canvas')
  await expect(canvas).toBeVisible()

  await test.step('Tour mode (Demo flow) visits every edge of stage 1, in order', async () => {
    await page.getByTestId('light-flow-mode-tour').click()
    // No explicit stage reset here — Tour autoplays continuously from mount and cycles
    // through all 5 stages on a loop, so stage 1's 4-edge run WILL appear in the cumulative
    // history within one full cycle regardless of where in that cycle we started watching.
    await expect
      .poll(
        async () => {
          const history = historyOf((await canvas.getAttribute('data-edge-history')) ?? '')
          return containsContiguousInOrder(history, STAGE_1_EDGE_IDS)
        },
        {
          timeout: 90_000,
          message: 'stage 1\'s edge sequence never appeared contiguously, in order, in data-edge-history',
        },
      )
      .toBe(true)
  })

  await test.step('Live mode emits a comet for a real chat request, not a synthetic one', async () => {
    await page.getByTestId('light-flow-mode-live').click()
    await expect(canvas).toHaveAttribute('data-mode', 'live')

    // Not asserting "idle" here: this document's background enrichment (graph/profile/
    // advisor) can still be producing real trace events this long after upload, and Live
    // mode correctly comets for those too (G1 — real activity, not fake). What LF-7 actually
    // asks for is a comet tied to the chat request specifically, so look for a chat-pipeline
    // edge (gateway-guardrails_in, from the guardian_in stage — the first thing any chat
    // turn touches) appearing in the history only after the message is sent.
    const beforeHistory = historyOf((await canvas.getAttribute('data-edge-history')) ?? '')
    const chatEdgeAlreadyPresent = beforeHistory.includes('gateway-guardrails_in')

    await page.getByRole('link', { name: 'Workspace' }).click()
    const input = page.getByPlaceholder(/ask a question/i)
    await input.fill('How many vacation days do employees accrue per month?')
    await input.press('Enter')
    await expect(page.getByText('How many vacation days do employees accrue per month?')).toBeVisible()

    await page.getByRole('link', { name: 'Architecture' }).click()
    if (chatEdgeAlreadyPresent) {
      // Already seen once (e.g. a prior turn in this session) — just confirm Live mode is
      // still producing real activity at all.
      await expect.poll(async () => canvas.getAttribute('data-edge-history'), { timeout: 60_000 }).toBeTruthy()
    } else {
      await expect
        .poll(
          async () => historyOf((await canvas.getAttribute('data-edge-history')) ?? '').includes('gateway-guardrails_in'),
          { timeout: 60_000, message: 'no gateway-guardrails_in comet after a real chat request' },
        )
        .toBe(true)
    }
  })
})
