import { useTheme } from "@/lib/theme"
import { Toaster as Sonner, type ToasterProps } from "sonner"
import { CircleCheckIcon, InfoIcon, TriangleAlertIcon, OctagonXIcon, Loader2Icon } from "lucide-react"

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme } = useTheme()

  return (
    <Sonner
      theme={theme}
      className="toaster group"
      icons={{
        success: (
          <CircleCheckIcon className="size-4" />
        ),
        info: (
          <InfoIcon className="size-4" />
        ),
        warning: (
          <TriangleAlertIcon className="size-4" />
        ),
        error: (
          <OctagonXIcon className="size-4" />
        ),
        loading: (
          <Loader2Icon className="size-4 animate-spin" />
        ),
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
          // Tint each status toast with our own success/warning/danger
          // tokens (same "N% tint over the surface" recipe as the Badge
          // success/warning/glow variants) instead of sonner's generic
          // green/amber/red defaults.
          "--success-bg": "color-mix(in srgb, var(--color-success) 12%, var(--popover))",
          "--success-border": "color-mix(in srgb, var(--color-success) 35%, transparent)",
          "--success-text": "var(--color-success)",
          "--warning-bg": "color-mix(in srgb, var(--color-warning) 12%, var(--popover))",
          "--warning-border": "color-mix(in srgb, var(--color-warning) 35%, transparent)",
          "--warning-text": "var(--color-warning)",
          "--error-bg": "color-mix(in srgb, var(--color-danger) 12%, var(--popover))",
          "--error-border": "color-mix(in srgb, var(--color-danger) 35%, transparent)",
          "--error-text": "var(--color-danger)",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "cn-toast",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
