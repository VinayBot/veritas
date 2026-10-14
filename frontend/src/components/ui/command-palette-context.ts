import { createContext, useContext, useEffect, type ReactNode } from 'react'

export interface CommandPaletteItem {
  id: string
  label: string
  icon?: ReactNode
  shortcut?: string
  group?: string
  /** Extra words to match on besides the label. */
  keywords?: string
  onSelect: () => void
}

export interface CommandPaletteContextValue {
  open: boolean
  setOpen: (open: boolean) => void
  register: (source: string, items: CommandPaletteItem[]) => void
  unregister: (source: string) => void
}

export const CommandPaletteContext = createContext<CommandPaletteContextValue | null>(null)

export function useCommandPalette(): CommandPaletteContextValue {
  const ctx = useContext(CommandPaletteContext)
  if (!ctx) throw new Error('useCommandPalette must be used within a <CommandPaletteProvider>')
  return ctx
}

/** Contributes commands for as long as the calling component is mounted. `items` should be
 * memoised by the caller; a new array re-registers. */
export function useCommands(source: string, items: CommandPaletteItem[]) {
  const { register, unregister } = useCommandPalette()
  useEffect(() => {
    register(source, items)
    return () => unregister(source)
  }, [source, items, register, unregister])
}

