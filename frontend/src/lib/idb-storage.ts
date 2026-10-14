/** Minimal IndexedDB-backed storage adapter for Zustand's `persist` middleware (Fix 1 — see
 * docs/DECISIONS.md). Hand-rolled rather than adding `idb-keyval` as a dependency — the surface
 * area this actually needs (get/set/remove one string value by key) is small enough that a
 * ~50-line adapter is simpler than configuring around a library, matching how the theme toggle
 * (frontend/src/lib/theme.tsx) already hand-rolled its own localStorage persistence instead of
 * pulling in next-themes.
 *
 * Every method is try/catch-guarded and resolves to a safe fallback rather than throwing:
 * IndexedDB can be unavailable or throw synchronously (private browsing, blocked site data,
 * a thumbnail/preview context), and persistence here is a per-viewer convenience, not state
 * anything else depends on being correct.
 */

import type { StateStorage } from 'zustand/middleware'

const DB_NAME = 'veritas-chat'
const STORE_NAME = 'kv'
const DB_VERSION = 1

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('indexedDB unavailable'))
      return
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE_NAME)) {
        req.result.createObjectStore(STORE_NAME)
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error ?? new Error('indexedDB open failed'))
  })
}

export const idbStorage: StateStorage = {
  async getItem(key: string): Promise<string | null> {
    try {
      const db = await openDb()
      return await new Promise<string | null>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readonly')
        const req = tx.objectStore(STORE_NAME).get(key)
        req.onsuccess = () => resolve((req.result as string | undefined) ?? null)
        req.onerror = () => reject(req.error)
      })
    } catch {
      return null
    }
  },

  async setItem(key: string, value: string): Promise<void> {
    try {
      const db = await openDb()
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite')
        tx.objectStore(STORE_NAME).put(value, key)
        tx.oncomplete = () => resolve()
        tx.onerror = () => reject(tx.error)
      })
    } catch {
      // Best-effort — see module docstring.
    }
  },

  async removeItem(key: string): Promise<void> {
    try {
      const db = await openDb()
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite')
        tx.objectStore(STORE_NAME).delete(key)
        tx.oncomplete = () => resolve()
        tx.onerror = () => reject(tx.error)
      })
    } catch {
      // Best-effort — see module docstring.
    }
  },
}
