import * as React from "react"
import { Dialog as DialogPrimitive } from "radix-ui"
import { AnimatePresence, motion, useReducedMotion } from "framer-motion"
import { XIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { SPRING_SOFT, DURATION } from "@/lib/motion"

type DrawerSide = "left" | "right" | "bottom"

// Radix's Root doesn't expose its resolved `open` state to descendants, but
// DrawerContent needs it to gate <AnimatePresence> (see below) — this is the
// one piece of local state that bridges the two.
const DrawerOpenContext = React.createContext(false)

function Drawer({
  open,
  onOpenChange,
  defaultOpen,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Root>) {
  const [internalOpen, setInternalOpen] = React.useState(defaultOpen ?? false)
  const resolvedOpen = open ?? internalOpen

  const handleOpenChange = (next: boolean) => {
    setInternalOpen(next)
    onOpenChange?.(next)
  }

  return (
    <DrawerOpenContext.Provider value={resolvedOpen}>
      <DialogPrimitive.Root
        data-slot="drawer"
        open={resolvedOpen}
        onOpenChange={handleOpenChange}
        {...props}
      />
    </DrawerOpenContext.Provider>
  )
}

function DrawerTrigger(props: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="drawer-trigger" {...props} />
}

function DrawerClose(props: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="drawer-close" {...props} />
}

const OFFSCREEN: Record<DrawerSide, { x?: string; y?: string }> = {
  right: { x: "100%" },
  left: { x: "-100%" },
  bottom: { y: "100%" },
}

const SIDE_CLASSNAME: Record<DrawerSide, string> = {
  right: "inset-y-0 right-0 h-full w-full max-w-sm border-l",
  left: "inset-y-0 left-0 h-full w-full max-w-sm border-r",
  bottom: "inset-x-0 bottom-0 max-h-[80vh] w-full rounded-t-[var(--radius-card)] border-t",
}

interface DrawerContentProps extends React.ComponentProps<typeof DialogPrimitive.Content> {
  side?: DrawerSide
  showCloseButton?: boolean
}

/**
 * A Dialog (installed via `npx shadcn add dialog`) repositioned as a
 * slide-over panel. Radix's own `forceMount` + an outer `<AnimatePresence>`
 * (gated on DrawerOpenContext, since Root doesn't expose `open` downward) is
 * the documented way to hand Dialog's enter/exit choreography to Framer
 * Motion instead of Radix's default CSS fade — see docs/UI_MOTION.md.
 */
function DrawerContent({
  side = "right",
  className,
  children,
  showCloseButton = true,
  ...props
}: DrawerContentProps) {
  const open = React.useContext(DrawerOpenContext)
  const reduced = useReducedMotion()
  const offscreen = OFFSCREEN[side]

  return (
    <AnimatePresence>
      {open && (
        <DialogPrimitive.Portal data-slot="drawer-portal" forceMount>
          <DialogPrimitive.Overlay asChild forceMount data-slot="drawer-overlay">
            <motion.div
              className="fixed inset-0 z-[var(--z-drawer)] bg-black/40 backdrop-blur-xs"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: reduced ? 0.001 : DURATION.base }}
            />
          </DialogPrimitive.Overlay>
          <DialogPrimitive.Content asChild forceMount data-slot="drawer-content" {...props}>
            <motion.div
              initial={reduced ? { opacity: 0 } : { ...offscreen, opacity: 1 }}
              animate={{ x: 0, y: 0, opacity: 1 }}
              exit={reduced ? { opacity: 0 } : { ...offscreen, opacity: 1 }}
              transition={reduced ? { duration: 0.001 } : SPRING_SOFT}
              className={cn(
                "fixed z-[var(--z-drawer)] flex flex-col gap-4 border-border bg-popover p-6 text-popover-foreground shadow-lg outline-none",
                SIDE_CLASSNAME[side],
                className,
              )}
            >
              {children}
              {showCloseButton && (
                <DialogPrimitive.Close
                  data-slot="drawer-close"
                  aria-label="Close drawer"
                  className="absolute top-4 right-4 rounded-md p-1 text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <XIcon className="size-4" />
                  <span className="sr-only">Close</span>
                </DialogPrimitive.Close>
              )}
            </motion.div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      )}
    </AnimatePresence>
  )
}

function DrawerHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div data-slot="drawer-header" className={cn("flex flex-col gap-1.5", className)} {...props} />
  )
}

function DrawerFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="drawer-footer"
      className={cn("mt-auto flex flex-col gap-2", className)}
      {...props}
    />
  )
}

function DrawerTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="drawer-title"
      className={cn("font-heading text-lg font-medium", className)}
      {...props}
    />
  )
}

function DrawerDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="drawer-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

export {
  Drawer,
  DrawerTrigger,
  DrawerClose,
  DrawerContent,
  DrawerHeader,
  DrawerFooter,
  DrawerTitle,
  DrawerDescription,
}
