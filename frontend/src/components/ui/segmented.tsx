import { cn } from '@/lib/utils'

/** A small set of mutually exclusive choices, rendered as a radio group. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
  testIdPrefix,
}: {
  value: T
  onChange: (value: T) => void
  options: { value: T; label: string; disabled?: boolean; title?: string }[]
  label: string
  className?: string
  testIdPrefix?: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn('inline-flex gap-1 rounded-pill bg-surface-raised p-1', className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          disabled={o.disabled}
          title={o.title}
          data-testid={testIdPrefix ? `${testIdPrefix}-${o.value}` : undefined}
          onClick={() => onChange(o.value)}
          className={cn(
            'rounded-pill px-3 py-1 text-xs font-medium transition-colors duration-micro disabled:cursor-not-allowed disabled:opacity-40',
            value === o.value ? 'bg-accent text-on-accent' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
