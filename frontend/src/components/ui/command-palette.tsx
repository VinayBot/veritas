import {
  createContext,
  Fragment,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { Sparkles, SunMoon } from 'lucide-react'
import { toast } from 'sonner'
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
  onSelect: () => void
}

interface CommandPaletteContextValue {
  open: boolean
  setOpen: (open: boolean) => void
}

const CommandPaletteContext = createContext<CommandPaletteContextValue | null>(null)

/** Lets any component (a header button, a menu item, ...) open the palette too, not just the Cmd/Ctrl+K binding. */
export function useCommandPalette(): CommandPaletteContextValue {
  const ctx = useContext(CommandPaletteContext)
  if (!ctx) throw new Error('useCommandPalette must be used within a <CommandPaletteProvider>')
  return ctx
}

/**
 * Owns the palette's open state, the global Cmd/Ctrl+K binding, and renders
 * the dialog itself — wrap the app with this once. Child components reach
 * the same state via useCommandPalette() (e.g. a visible "⌘K" header button).
 */
export function CommandPaletteProvider({
  children,
  items = [],
}: {
  children: ReactNode
  items?: CommandPaletteItem[]
}) {
  const [open, setOpen] = useState(false)
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

  const value = useMemo(() => ({ open, setOpen }), [open])

  const builtins: CommandPaletteItem[] = [
    {
      id: 'toggle-theme',
      label: 'Toggle dark / light theme',
      icon: <SunMoon className="size-4" />,
      shortcut: 'T',
      group: 'Appearance',
      onSelect: toggleTheme,
    },
    {
      id: 'show-toast',
      label: 'Show an example toast',
      icon: <Sparkles className="size-4" />,
      group: 'Demo',
      onSelect: () =>
        toast('This is an example toast', {
          description: 'Triggered from the command palette.',
        }),
    },
  ]

  const allItems = [...builtins, ...items]
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
          <CommandInput placeholder="Type a command or search…" aria-label="Search commands" />
          <CommandList>
            <CommandEmpty>No results found.</CommandEmpty>
            {groups.map((group, index) => (
              <Fragment key={group}>
                {index > 0 && <CommandSeparator />}
                <CommandGroup heading={group}>
                  {allItems
                    .filter((item) => (item.group ?? 'General') === group)
                    .map((item) => (
                      <CommandItem
                        key={item.id}
                        onSelect={() => {
                          item.onSelect()
                          setOpen(false)
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
