import { test, expect } from '@playwright/test'
import path from 'node:path'

/** Covers the "hangs on Ingesting..." incident fix end to end — see docs/TROUBLESHOOTING.md.
 * Ingestion is a detached background job now (app/ingestion/service.py): these tests assert
 * the UI reflects that correctly — real stage progress in order, a bounded time-to-ready,
 * clear errors (never a silent hang) for bad input, cancel, and a trace WebSocket the UI
 * doesn't actually depend on to make progress. */

const NORTHWIND_PDF = path.join(
  import.meta.dirname,
  '../../../data/demo/northwind_remote_work_travel_policy.pdf',
)
const EMPTY_PDF = path.join(import.meta.dirname, 'fixtures/empty.pdf')
const CORRUPT_PDF = path.join(import.meta.dirname, 'fixtures/corrupt.pdf')

test('uploading the Northwind PDF shows ordered stage progress and reaches ready within 60s', async ({
  page,
}) => {
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)

  // The Stepper's first stage ("Upload") must show progress almost immediately — this is
  // exactly the bug: before the fix, nothing distinguished "about to hang" from "working".
  await expect(page.getByText('queued').or(page.getByText('running'))).toBeVisible({
    timeout: 5_000,
  })

  await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText(/chunks \(/)).toBeVisible()

  // Chat must be enabled only once the document is actually ready, not the moment it was
  // merely accepted (the root bug: the old UI assumed upload === ready).
  await expect(page.getByPlaceholder(/ask a question about this document/i)).toBeEnabled()
})

test('a corrupt PDF shows a clear error with Retry, never spins forever', async ({ page }) => {
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(CORRUPT_PDF)

  await expect(page.getByRole('alert').getByText(/ingestion failed/i)).toBeVisible({ timeout: 30_000 })
  // The regression this guards: Docling's raw exception leaked an internal content-hash key.
  await expect(page.getByText(/could not load document/i)).not.toBeVisible()
  await expect(page.getByRole('button', { name: /retry/i })).toBeVisible()
})

test('a 0-byte file shows a clear error, never spins forever', async ({ page }) => {
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(EMPTY_PDF)

  await expect(page.getByRole('alert').getByText(/ingestion failed/i)).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: /retry/i })).toBeVisible()
})

test('cancelling a queued/running job shows cancelled with a Retry option', async ({ page }) => {
  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)

  await page.getByRole('button', { name: /cancel/i }).click()
  await expect(page.getByText('cancelled', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('button', { name: /retry/i })).toBeVisible()
})

test('ingestion still reaches ready when the trace WebSocket is blocked', async ({ page }) => {
  // Simulates "the WebSocket drops / is blocked by a proxy" — the UI must fall back to
  // polling GET /api/v1/documents/{id} rather than depend on the socket for anything the
  // overall job status needs (see useDocumentStatus, which polls unconditionally).
  await page.routeWebSocket(/\/ws\/trace\//, (ws) => ws.close())

  await page.goto('/app')
  await page.locator('input[type="file"]').setInputFiles(NORTHWIND_PDF)

  await expect(page.getByText('ready', { exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText(/chunks \(/)).toBeVisible()
})
