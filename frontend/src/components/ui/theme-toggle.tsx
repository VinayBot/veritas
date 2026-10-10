import { Moon, Sun } from 'lucide-react'
import { motion, useReducedMotion } from 'framer-motion'
import { useTheme } from '@/lib/theme'
import { SPRING, reducedTransition } from '@/lib/motion'
import { cn } from '@/lib/utils'

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useTheme()
  const reduced = useReducedMotion()
  const isLight = theme === 'light'

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isLight}
      aria-label={isLight ? 'Switch to dark theme' : 'Switch to light theme'}
      onClick={toggleTheme}
      className={cn(
        'relative inline-flex h-8 w-14 shrink-0 cursor-pointer items-center rounded-pill border border-border bg-surface-raised p-1 transition-colors duration-240',
        className,
      )}
    >
      <Sun
        aria-hidden="true"
        className="absolute left-1.5 size-4 text-muted-foreground"
      />
      <Moon
        aria-hidden="true"
        className="absolute right-1.5 size-4 text-muted-foreground"
      />
      <motion.span
        aria-hidden="true"
        className="relative z-10 flex size-6 items-center justify-center rounded-full bg-accent text-on-accent shadow-sm"
        animate={{ x: isLight ? 24 : 0 }}
        transition={reducedTransition(!!reduced, SPRING)}
      >
        {isLight ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
      </motion.span>
      <span className="sr-only">{isLight ? 'Light theme active' : 'Dark theme active'}</span>
    </button>
  )
}
