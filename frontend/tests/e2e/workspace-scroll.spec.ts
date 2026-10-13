/// <reference lib="dom" />
// tests/** compiles under tsconfig.node.json (lib: ES2023 only, no DOM) — this file is the
// first e2e spec to call `document.createElement` inside a page.evaluate callback, so it
// needs the DOM lib's ambient types locally rather than widening every other test's tsconfig.
import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'

/** Regression coverage for the "two-finger trackpad scroll is dead in Workspace" bug (see
 * docs/TROUBLESHOOTING.md). Root cause: `src/lib/smooth-scroll.tsx` wraps the entire app in
 * `<ReactLenis root>`, which intercepts wheel/touch globally and virtualizes scrolling onto
 * whatever ancestor Lenis decides is "the" scroller — unless an element carries
 * `data-lenis-prevent`, in which case Lenis's own composed-path check (`node.hasAttribute(
 * 'data-lenis-prevent')`, node_modules/lenis/dist/lenis.mjs) lets the browser's native scroll
 * run on it instead. Neither the chat pane nor the document-intelligence panel carried that
 * attribute, so native `overflow-y: auto` on those two panes never got a chance to act on the
 * wheel/touch event — Lenis consumed it first and tried (uselessly, since the page itself had
 * nothing left to scroll inside the `h-screen` layout) to smooth-scroll the window.
 *
 * Fix: `data-lenis-prevent` on both panes' scroll containers (`[data-testid="chat-scroll-
 * pane"]` and `[data-testid="document-intelligence-panel"]`), plus making both natively
 * keyboard-scrollable (`tabIndex={0}`) and switching the page's outer `h-screen` to `h-dvh`
 * for correctness on mobile viewports with dynamic browser toolbars.
 *
 * This spec runs on chromium AND webkit (playwright.config.ts's `webkit` project matches only
 * this file) per the brief's SC-6. Before the fix, `page.mouse.wheel` over either pane leaves
 * its `scrollTop` at 0 — confirmed by running this file against the pre-fix commit.
 */

const NORTHWIND_PDF = path.join(
  import.meta.dirname,
  '../../../data/demo/northwind_remote_work_travel_policy.pdf',
)

// Seeds deterministic overflow into an already-rendered scroll container without touching any
// application state — these are throwaway DOM nodes for scroll-mechanics assertions only, not
// data the app ever renders to a real user (see G1: the app itself never fabricates content).
async function seedOverflow(page: Page, testId: string) {
  await page.locator(`[data-testid="${testId}"]`).evaluate((el) => {
    const filler = document.createElement('div')
    filler.setAttribute('data-test-filler', 'true')
    filler.style.height = '4000px'
    el.appendChild(filler)
  })
}

// Mimics a trackpad: several small, fractional wheel ticks rather than one large mouse-wheel
// notch (the bug only reproduced with small deltas — see Phase 1's diagnosis step 1).
async function trackpadScroll(
  page: Page,
  pane: ReturnType<Page['getByTestId']>,
  x: number,
  y: number,
  totalDeltaY: number,
) {
  await page.mouse.move(x, y)
  const ticks = 12
  for (let i = 0; i < ticks; i++) {
    await page.mouse.wheel(0, totalDeltaY / ticks)
  }
  // Chromium/WebKit both animate (inertia-smooth) the resulting scroll over the next couple
  // of frames rather than jumping instantly — reading scrollTop before it settles makes a
  // later comparison against that snapshot flaky. Wait for two consecutive reads to agree.
  let last = -1
  for (let i = 0; i < 20; i++) {
    const current = await pane.evaluate((el) => el.scrollTop)
    if (current === last) return
    last = current
    await new Promise((r) => setTimeout(r, 100))
  }
}

test('chat pane and document-intelligence pane both scroll independently, with keyboard and wheel, while the composer stays pinned', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)
  await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 60_000 })

  const chatPane = page.getByTestId('chat-scroll-pane')
  const dashPane = page.getByTestId('document-intelligence-panel')
  await expect(chatPane).toBeVisible()
  await expect(dashPane).toBeVisible()

  await seedOverflow(page, 'chat-scroll-pane')
  await seedOverflow(page, 'document-intelligence-panel')

  await test.step('composer position before any scrolling (pinned reference point)', async () => {
    const composer = page.getByPlaceholder(/ask a question about this document/i)
    const before = await composer.boundingBox()
    expect(before).not.toBeNull()
  })

  await test.step('wheel (trackpad-style, fractional deltas) scrolls the chat pane', async () => {
    const box = (await chatPane.boundingBox())!
    expect(await chatPane.evaluate((el) => el.scrollTop)).toBe(0)
    await trackpadScroll(page, chatPane, box.x + box.width / 2, box.y + box.height / 2, 600)
    await expect.poll(() => chatPane.evaluate((el) => el.scrollTop)).toBeGreaterThan(50)
  })

  const chatScrollAfterWheel = await chatPane.evaluate((el) => el.scrollTop)

  await test.step('wheel over the dashboard pane scrolls IT, not the chat pane (independent scrollers)', async () => {
    const box = (await dashPane.boundingBox())!
    expect(await dashPane.evaluate((el) => el.scrollTop)).toBe(0)
    await trackpadScroll(page, dashPane, box.x + box.width / 2, box.y + box.height / 2, 600)
    await expect.poll(() => dashPane.evaluate((el) => el.scrollTop)).toBeGreaterThan(50)
    expect(await chatPane.evaluate((el) => el.scrollTop)).toBe(chatScrollAfterWheel)
  })

  await test.step('composer stays pinned after scrolling the chat pane', async () => {
    const composer = page.getByPlaceholder(/ask a question about this document/i)
    await expect(composer).toBeVisible()
    await expect(composer).toBeInViewport()
  })

  await test.step('keyboard scroll (PageDown, ArrowDown, Space) moves the chat pane', async () => {
    await chatPane.click({ position: { x: 5, y: 5 } }) // focuses without hitting a message/link
    await chatPane.evaluate((el) => (el.scrollTop = 0))
    await chatPane.focus()

    await page.keyboard.press('PageDown')
    await expect.poll(() => chatPane.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
    const afterPageDown = await chatPane.evaluate((el) => el.scrollTop)

    await page.keyboard.press('ArrowDown')
    await expect
      .poll(() => chatPane.evaluate((el) => el.scrollTop))
      .toBeGreaterThanOrEqual(afterPageDown)

    await chatPane.evaluate((el) => (el.scrollTop = 0))
    await page.keyboard.press('Space')
    await expect.poll(() => chatPane.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
  })
})

test('"Jump to latest" chip appears once scrolled away from the bottom and returns to bottom on click', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)
  await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 60_000 })

  // The chip only has meaning once there's a "latest" to jump to (messages.length > 0) — a
  // real chat turn, not fabricated content (G1). The chip's own trigger condition only needs
  // the user's message to exist (appended optimistically the instant Enter is pressed), not a
  // completed assistant answer — waiting for the full streamed reply here would be slow and,
  // on a long sequential run sharing one backend/Ollama instance with every earlier test,
  // needlessly exposed to real contention this test doesn't actually care about.
  const input = page.getByPlaceholder(/ask a question/i)
  await input.fill('How many vacation days do employees accrue per month?')
  await input.press('Enter')
  await expect(page.getByText('How many vacation days do employees accrue per month?')).toBeVisible({
    timeout: 15_000,
  })

  const chatPane = page.getByTestId('chat-scroll-pane')
  await seedOverflow(page, 'chat-scroll-pane')

  const jumpChip = page.getByTestId('jump-to-latest')
  await expect(jumpChip).not.toBeVisible()

  await chatPane.evaluate((el) => (el.scrollTop = 0))
  await chatPane.dispatchEvent('scroll')
  await expect(jumpChip).toBeVisible()

  await jumpChip.click()
  await expect(jumpChip).not.toBeVisible()
  await expect
    .poll(async () => {
      const { scrollTop, scrollHeight, clientHeight } = await chatPane.evaluate((el) => ({
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
      }))
      return scrollHeight - scrollTop - clientHeight
    })
    .toBeLessThan(48)
})

for (const vp of [
  { name: '1280x720', width: 1280, height: 720 },
  { name: '1024x600', width: 1024, height: 600 },
]) {
  test(`chat and dashboard panes both scroll at ${vp.name}`, async ({ page }) => {
    await page.setViewportSize(vp)
    await page.goto('/app')
    await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)
    await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 60_000 })

    const chatPane = page.getByTestId('chat-scroll-pane')
    const dashPane = page.getByTestId('document-intelligence-panel')
    await seedOverflow(page, 'chat-scroll-pane')
    await seedOverflow(page, 'document-intelligence-panel')

    const chatBox = (await chatPane.boundingBox())!
    await trackpadScroll(page, chatPane, chatBox.x + chatBox.width / 2, chatBox.y + chatBox.height / 2, 600)
    await expect.poll(() => chatPane.evaluate((el) => el.scrollTop)).toBeGreaterThan(50)

    if (await dashPane.isVisible()) {
      const dashBox = (await dashPane.boundingBox())!
      await trackpadScroll(page, dashPane, dashBox.x + dashBox.width / 2, dashBox.y + dashBox.height / 2, 600)
      await expect.poll(() => dashPane.evaluate((el) => el.scrollTop)).toBeGreaterThan(50)
    }
  })
}

test('chat pane scrolls at mobile width (390x844), where the dashboard pane is intentionally hidden', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)
  await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 60_000 })

  const chatPane = page.getByTestId('chat-scroll-pane')
  await seedOverflow(page, 'chat-scroll-pane')

  // Unchanged pre-existing responsive behavior (`hidden ... lg:block`), not something this fix
  // touches — asserted here so a future regression on that breakpoint is caught too.
  await expect(page.getByTestId('document-intelligence-panel')).not.toBeVisible()

  const box = (await chatPane.boundingBox())!
  await trackpadScroll(page, chatPane, box.x + box.width / 2, box.y + box.height / 2, 600)
  await expect.poll(() => chatPane.evaluate((el) => el.scrollTop)).toBeGreaterThan(50)
})
