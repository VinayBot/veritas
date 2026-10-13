import { useId } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { cn } from '@/lib/utils'

export type BotState = 'idle' | 'working' | 'success' | 'error'

const STATE_LABEL: Record<BotState, string> = {
  idle: 'standing by',
  working: 'working',
  success: 'done',
  error: 'something failed',
}

/**
 * The analyst: a hovering sentinel in lacquer armour. Its state is driven by what the app is
 * really doing — it scans while a document is being ingested or a question answered, settles
 * when the work is done, and turns red when something fails. All motion is transform or
 * opacity; with reduced motion it holds a still pose and the state is carried by colour and
 * the text label alone.
 */
export function AnalystBot({
  state = 'idle',
  size = 168,
  label,
  className,
}: {
  state?: BotState
  size?: number
  /** What it is doing, in words; read out and shown beneath. */
  label?: string
  className?: string
}) {
  const reduced = useReducedMotion()
  const uid = useId().replace(/:/g, '')
  const working = state === 'working'
  const eye = state === 'error' ? 'var(--color-danger)' : state === 'success' ? 'var(--color-gold)' : 'var(--color-live)'
  const loop = (duration: number) => ({ duration, repeat: Infinity, ease: 'easeInOut' as const })
  const spin = (duration: number) => ({ duration, repeat: Infinity, ease: 'linear' as const })

  return (
    <figure
      className={cn('flex flex-col items-center gap-2', className)}
      data-testid="analyst-bot"
      data-state={state}
      role="img"
      aria-label={`Analyst: ${label ?? STATE_LABEL[state]}`}
    >
      <svg width={size} height={size} viewBox="0 0 200 200" overflow="visible">
        <defs>
          <linearGradient id={`${uid}-armor`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#3a3640" />
            <stop offset="0.55" stopColor="#1d1b22" />
            <stop offset="1" stopColor="#0f0e13" />
          </linearGradient>
          <linearGradient id={`${uid}-lacquer`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--color-accent)" />
            <stop offset="1" stopColor="#7a0f19" />
          </linearGradient>
          <linearGradient id={`${uid}-gold`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#f6dc9a" />
            <stop offset="1" stopColor="var(--color-gold)" />
          </linearGradient>
          <radialGradient id={`${uid}-core`}>
            <stop offset="0" stopColor="#ffffff" />
            <stop offset="0.35" stopColor={eye} />
            <stop offset="1" stopColor={eye} stopOpacity="0" />
          </radialGradient>
          <radialGradient id={`${uid}-ground`}>
            <stop offset="0" stopColor={eye} stopOpacity="0.45" />
            <stop offset="1" stopColor={eye} stopOpacity="0" />
          </radialGradient>
          <clipPath id={`${uid}-visor`}>
            <rect x="66" y="58" width="68" height="20" rx="10" />
          </clipPath>
        </defs>

        {/* Ground glow: breathes with the hover. */}
        <motion.ellipse
          cx="100"
          cy="184"
          rx="46"
          ry="9"
          fill={`url(#${uid}-ground)`}
          animate={reduced ? undefined : { scaleX: [1, 0.82, 1], opacity: [0.9, 0.55, 0.9] }}
          transition={loop(working ? 1.6 : 3.2)}
          style={{ transformOrigin: '100px 184px' }}
        />

        {/* Orbit rings: only while working. */}
        {working && (
          <g opacity="0.85">
            <motion.ellipse
              cx="100"
              cy="112"
              rx="78"
              ry="20"
              fill="none"
              stroke="var(--color-live)"
              strokeWidth="1.2"
              strokeDasharray="6 10"
              animate={reduced ? undefined : { rotate: 360 }}
              transition={spin(7)}
              style={{ transformOrigin: '100px 112px' }}
            />
            <motion.ellipse
              cx="100"
              cy="112"
              rx="64"
              ry="14"
              fill="none"
              stroke="var(--color-gold)"
              strokeWidth="1"
              strokeDasharray="2 12"
              animate={reduced ? undefined : { rotate: -360 }}
              transition={spin(5)}
              style={{ transformOrigin: '100px 112px' }}
            />
          </g>
        )}

        <motion.g
          animate={
            reduced
              ? undefined
              : state === 'error'
                ? { x: [0, -4, 4, -3, 3, 0], y: 0 }
                : { y: [0, -7, 0] }
          }
          transition={state === 'error' ? { duration: 0.4 } : loop(working ? 1.6 : 3.2)}
        >
          {/* Thruster */}
          <motion.path
            d="M88 150 L100 176 L112 150 Z"
            fill={eye}
            opacity="0.55"
            animate={reduced ? undefined : { scaleY: [1, 1.35, 0.9, 1], opacity: [0.55, 0.85, 0.4, 0.55] }}
            transition={loop(working ? 0.35 : 0.7)}
            style={{ transformOrigin: '100px 150px' }}
          />

          {/* Floating gauntlets */}
          {[-1, 1].map((side) => (
            <motion.g
              key={side}
              animate={reduced ? undefined : { y: [0, working ? -8 : -3, 0], rotate: [0, side * (working ? 10 : 3), 0] }}
              transition={{ ...loop(working ? 1.1 : 2.6), delay: side === 1 ? 0.25 : 0 }}
              style={{ transformOrigin: `${100 + side * 58}px 122px` }}
            >
              <rect x={100 + side * 58 - 9} y="108" width="18" height="26" rx="8" fill={`url(#${uid}-armor)`} stroke="#4a4551" />
              <rect x={100 + side * 58 - 9} y="108" width="18" height="6" rx="3" fill={`url(#${uid}-lacquer)`} />
            </motion.g>
          ))}

          {/* Torso: layered plates narrowing to the thruster */}
          <path d="M64 98 Q100 86 136 98 L128 138 Q100 152 72 138 Z" fill={`url(#${uid}-armor)`} stroke="#4a4551" />
          <path d="M70 104 Q100 95 130 104 L127 114 Q100 106 73 114 Z" fill={`url(#${uid}-lacquer)`} />
          <path d="M74 120 Q100 112 126 120 L124 128 Q100 121 76 128 Z" fill="#26232b" stroke="#3d3944" />
          {/* Shoulder guards */}
          <path d="M58 96 Q52 84 70 86 L78 96 Q66 98 58 104 Z" fill={`url(#${uid}-lacquer)`} stroke="#4a1016" />
          <path d="M142 96 Q148 84 130 86 L122 96 Q134 98 142 104 Z" fill={`url(#${uid}-lacquer)`} stroke="#4a1016" />

          {/* Core */}
          <motion.circle
            cx="100"
            cy="132"
            r="11"
            fill={`url(#${uid}-core)`}
            animate={reduced ? undefined : { scale: working ? [1, 1.35, 1] : [1, 1.12, 1], opacity: [0.85, 1, 0.85] }}
            transition={loop(working ? 0.7 : 2.4)}
            style={{ transformOrigin: '100px 132px' }}
          />

          {/* Head */}
          <motion.g
            animate={reduced ? undefined : { rotate: working ? [-4, 4, -4] : [-1.5, 1.5, -1.5] }}
            transition={loop(working ? 1.8 : 5)}
            style={{ transformOrigin: '100px 86px' }}
          >
            {/* Helmet crest */}
            <path d="M100 20 C84 30 74 42 70 52 L78 50 C84 40 92 32 100 28 C108 32 116 40 122 50 L130 52 C126 42 116 30 100 20 Z" fill={`url(#${uid}-gold)`} />
            <circle cx="100" cy="36" r="4" fill={`url(#${uid}-gold)`} />
            {/* Helmet bowl and flared neck guard */}
            <path d="M62 62 Q62 36 100 36 Q138 36 138 62 L138 72 Q100 64 62 72 Z" fill={`url(#${uid}-armor)`} stroke="#4a4551" />
            <path d="M54 76 Q100 62 146 76 L140 86 Q100 74 60 86 Z" fill={`url(#${uid}-lacquer)`} stroke="#4a1016" />
            {/* Face plate */}
            <rect x="62" y="52" width="76" height="34" rx="14" fill="#0b0a0e" stroke="#3d3944" />
            {/* Visor */}
            <rect x="66" y="58" width="68" height="20" rx="10" fill="#050507" />
            <g clipPath={`url(#${uid}-visor)`}>
              {state === 'success' ? (
                <g stroke={eye} strokeWidth="4" strokeLinecap="round" fill="none">
                  <path d="M78 72 Q85 62 92 72" />
                  <path d="M108 72 Q115 62 122 72" />
                </g>
              ) : state === 'error' ? (
                <g stroke={eye} strokeWidth="4" strokeLinecap="round">
                  <path d="M78 63 L92 73 M92 63 L78 73" />
                  <path d="M108 63 L122 73 M122 63 L108 73" />
                </g>
              ) : working ? (
                <motion.rect
                  y="58"
                  width="22"
                  height="20"
                  fill={eye}
                  animate={reduced ? { x: 89 } : { x: [60, 118, 60] }}
                  transition={loop(1.1)}
                  style={{ filter: 'blur(1px)' }}
                />
              ) : (
                <motion.g
                  animate={reduced ? undefined : { scaleY: [1, 1, 0.1, 1, 1] }}
                  transition={{ duration: 4.5, repeat: Infinity, times: [0, 0.9, 0.94, 0.98, 1] }}
                  style={{ transformOrigin: '100px 68px' }}
                >
                  <rect x="76" y="64" width="18" height="8" rx="4" fill={eye} />
                  <rect x="106" y="64" width="18" height="8" rx="4" fill={eye} />
                </motion.g>
              )}
            </g>
          </motion.g>

          {/* Embers shed while working */}
          {working &&
            !reduced &&
            [0, 1, 2, 3].map((i) => (
              <motion.circle
                key={i}
                cx={72 + i * 19}
                cy="150"
                r="1.8"
                fill="var(--color-gold)"
                initial={{ opacity: 0 }}
                animate={{ y: [0, -70], opacity: [0, 0.9, 0] }}
                transition={{ duration: 1.8, repeat: Infinity, delay: i * 0.4, ease: 'easeOut' }}
              />
            ))}
        </motion.g>
      </svg>
      {label && <figcaption className="text-center text-xs text-muted-foreground">{label}</figcaption>}
    </figure>
  )
}
