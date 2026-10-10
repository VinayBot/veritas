import { cn } from "cn"

/**
 * Loading placeholder with a translateX shimmer sweep (.skeleton-shimmer in
 * index.css) instead of a plain opacity pulse — purely transform-driven, and
 * collapsed by the global prefers-reduced-motion rule like every other
 * animation in this app. Shape it with className (h-4 w-24, rounded-full
 * for an avatar, ...); it intentionally has no status prop of its own, since
 * "loading placeholder" is the one thing it represents — components that
 * render *this* for their own loading state are the ones with a status prop.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("skeleton-shimmer rounded-md", className)}
      {...props}
    />
  )
}

export { Skeleton }
