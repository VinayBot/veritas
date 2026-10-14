# Veritas frontend

React 19 + TypeScript + Vite, styled with Tailwind v4. Three tabs, all on live backend data:
**Workspace** (`src/pages/workspace-page.tsx`), **Architecture** (`architecture-page.tsx`) and
**Evaluation** (`evaluation-page.tsx`), plus the landing page.

- `src/lib/api/`: typed API client (REST, server-sent events for streamed answers, WebSocket
  for live traces); types mirror the backend's Pydantic schemas.
- `src/components/`: workspace, compare, architecture, evaluation, charts and a small design
  system in `ui/`.
- `src/store/`: Zustand state (chat history is kept per document in the browser).

```bash
npm install
npm run dev     # http://localhost:5173/app, proxies /api and /ws to the backend on :8000
npm test        # Vitest unit tests
npm run lint    # oxlint
npm run build   # type-check and production build
npx playwright test   # end-to-end, see tests/e2e/README.md
```
