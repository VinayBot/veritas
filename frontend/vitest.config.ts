import path from 'node:path'
import { defineConfig } from 'vitest/config'

/** Minimal vitest setup, added specifically to host the Architecture System Design
 * contract test (AR-5) — no unit test runner existed in this project before. 'node'
 * environment, not 'jsdom': the two test files here are pure data/consistency checks, not
 * component renders. */
export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
