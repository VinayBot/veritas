import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ThemeContext, type Theme } from './theme-context'

/** Keep in sync with the inline bootstrap script in index.html. */
export const THEME_STORAGE_KEY = 'veritas:theme'

function writeStoredTheme(theme: Theme) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Same as above — persistence is best-effort.
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // The inline script in index.html already applied (or didn't apply) the
  // `.light` class before React ever mounted, specifically to avoid a
  // flash-of-wrong-theme. Read that back as the initial state instead of
  // re-reading localStorage, so this is a continuation of the same decision
  // rather than a second, possibly-racing source of truth.
  const [theme, setThemeState] = useState<Theme>(() =>
    typeof document !== 'undefined' && document.documentElement.classList.contains('light')
      ? 'light'
      : 'dark',
  )

  useEffect(() => {
    document.documentElement.classList.toggle('light', theme === 'light')
  }, [theme])

  // Stable identities (useCallback) so the context value only changes when
  // `theme` itself does, and so the toggle reads the *previous* state via
  // the updater form instead of closing over a possibly-stale `theme`.
  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    writeStoredTheme(next)
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark'
      writeStoredTheme(next)
      return next
    })
  }, [])

  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [theme, setTheme, toggleTheme])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// NOTE: index.html has a tiny inline <script> that duplicates the read half
// of this logic (localStorage.getItem('veritas:theme') -> add .light),
// guarded the same way, so the correct theme class is on <html> before React
// (or any CSS) ever paints. It can't import this module — plain HTML runs
// before Vite/React exist — so if THEME_STORAGE_KEY's value ever changes,
// update that script's literal string too.
