import type { ReactNode } from 'react'
import { Button } from './button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from './dialog'

/** Confirmation for anything destructive or expensive. `cost` states what it will take. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  cost,
  confirmLabel = 'Confirm',
  destructive,
  onConfirm,
  busy,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: ReactNode
  cost?: ReactNode
  confirmLabel?: string
  destructive?: boolean
  onConfirm: () => void
  busy?: boolean
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="confirm-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription asChild>
            <div className="flex flex-col gap-3 text-sm text-muted-foreground">
              <div>{description}</div>
              {cost && (
                <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-foreground" data-testid="confirm-cost">
                  {cost}
                </div>
              )}
            </div>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant={destructive ? 'destructive' : 'default'} onClick={onConfirm} disabled={busy} data-testid="confirm-accept">
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
