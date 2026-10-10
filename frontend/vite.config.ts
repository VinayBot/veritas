import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Overridable so a test run can point at an isolated backend instance instead of always
// colliding with whatever's on the default dev port (see docs/DECISIONS.md's test-isolation
// entry) — defaults match the normal `make dev` setup, so nothing changes for local dev.
const backendPort = process.env.VITE_BACKEND_PORT ?? '8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': { target: `http://localhost:${backendPort}`, changeOrigin: true },
      '/ws': { target: `ws://localhost:${backendPort}`, ws: true },
    },
  },
})
