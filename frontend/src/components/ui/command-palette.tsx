import {
  createContext,
  Fragment,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { SunMoon } from 'lucide-react'
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from './command'
import { useTheme } from '@/lib/theme'

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

interface CommandPaletteContextValue {
  open: boolean
  setOpen: (open: boolean) => void
  register: (source: string, items: CommandPaletteItem[]) => void
  unregister: (source: string) => void
}

const CommandPaletteContext = createContext<CommandPaletteContextValue | null>(null)

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

/**
 * Owns the palette's open state, the global Cmd/Ctrl+K binding and the dialog itself. Any
 * component under it adds real actions with useCommands().
 */
export function CommandPaletteProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [sources, setSources] = useState<Record<string, CommandPaletteItem[]>>({})
  const { toggleTheme } = useTheme()

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        setOpen((prev) => !prev)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  const register = useCallback((source: string, items: CommandPaletteItem[]) => {
    setSources((prev) => ({ ...prev, [source]: items }))
  }, [])
  const unregister = useCallback((source: string) => {
    setSources((prev) => {
      if (!(source in prev)) return prev
      const next = { ...prev }
      delete next[source]
      return next
    })
  }, [])

  const value = useMemo(() => ({ open, setOpen, register, unregister }), [open, register, unregister])

  const allItems = useMemo<CommandPaletteItem[]>(
    () => [
      ...Object.values(sources).flat(),
      {
        id: 'toggle-theme',
        label: 'Toggle dark / light theme',
        icon: <SunMoon className="size-4" />,
        group: 'Appearance',
        onSelect: toggleTheme,
      },
    ],
    [sources, toggleTheme],
  )
  const groups = Array.from(new Set(allItems.map((item) => item.group ?? 'General')))

  return (
    <CommandPaletteContext.Provider value={value}>
      {children}
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        title="Command palette"
        description="Search for an action and run it"
      >
        <Command>
          <CommandInput placeholder="Jump to a tab, switch strategy or model, run a check…" aria-label="Search commands" />
          <CommandList>
            <CommandEmpty>No matching command.</CommandEmpty>
            {groups.map((group, index) => (
              <Fragment key={group}>
                {index > 0 && <CommandSeparator />}
                <CommandGroup heading={group}>
                  {allItems
                    .filter((item) => (item.group ?? 'General') === group)
                    .map((item) => (
                      <CommandItem
                        key={item.id}
                        value={`${item.label} ${item.keywords ?? ''}`}
                        data-testid={`command-${item.id}`}
                        onSelect={() => {
                          setOpen(false)
                          item.onSelect()
                        }}
                      >
                        {item.icon}
                        <span>{item.label}</span>
                        {item.shortcut && <CommandShortcut>{item.shortcut}</CommandShortcut>}
                      </CommandItem>
                    ))}
                </CommandGroup>
              </Fragment>
            ))}
          </CommandList>
        </Command>
      </CommandDialog>
    </CommandPaletteContext.Provider>
  )
}
