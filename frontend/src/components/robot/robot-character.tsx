import { motion, useReducedMotion, type Transition } from 'framer-motion'
import { useMemo } from 'react'
import { cn } from '@/lib/utils'

/**
 * The shared robot puppet (see docs/DECISIONS.md's "robot rig" entry for why this is a plain
 * layered SVG + Framer Motion rather than a 3D glTF pipeline): a glossy white body, dark glass
 * visor with glowing eyes, soft-glow ear rings, two-segment arms/legs. One component, reused
 * at full scale in the Architecture tab's courier and at 60% scale for its parallel-retrieval
 * helpers, and again (standing still) as the Workspace panel's analyst.
 *
 * `state` drives real, data-true behavior — see each call site for what sets it; this
 * component only ever renders what it's told, never invents its own timer-driven state.
 */
export type RobotState =
  | 'idle'
  | 'walk'
  | 'working'
  | 'celebrate'
  | 'error'
  | 'shield'
  | 'sad'

export interface RobotCharacterProps {
  state: RobotState
  /** Mirrors facing direction to the real direction of travel — never guessed. */
  facing?: 'left' | 'right'
  /** Renders a small box between the hands, labelled with the real filename/size. */
  carrying?: { label: string } | null
  scale?: number
  className?: string
  /** Exposed verbatim as data-robot-state / data-robot-action per the brief's test-hook
   * requirement (Section 11) — DOM-inspectable without reaching into component internals. */
  action?: string | null
}

const EYE_GLOW_FILTER = 'robot-eye-glow'
const EAR_GLOW_FILTER = 'robot-ear-glow'

export function RobotCharacter({
  state,
  facing = 'right',
  carrying,
  scale = 1,
  className,
  action,
}: RobotCharacterProps) {
  const reduced = useReducedMotion()
  const t = (transition: Transition): Transition => (reduced ? { duration: 0.001 } : transition)

  const bodyAnimate = useMemo(() => {
    switch (state) {
      case 'walk':
        return { y: [0, -3, 0], rotate: [0, 1, -1, 0] }
      case 'working':
        return { y: [0, -2, 0] }
      case 'celebrate':
        return { y: [0, -22, 0, -10, 0], rotate: [0, -6, 6, -3, 0] }
      case 'error':
      case 'sad':
        return { x: [0, -4, 4, -2, 0], rotate: [0, -2, 2, 0] }
      case 'shield':
        return { y: [0, -1, 0] }
      default:
        return { y: [0, -1.5, 0] }
    }
  }, [state])

  const bodyTransition: Transition = t(
    state === 'celebrate'
      ? { duration: 0.9, ease: 'easeOut' }
      : state === 'error' || state === 'sad'
        ? { duration: 0.4, ease: 'easeInOut' }
        : { duration: state === 'walk' ? 0.5 : 2.2, repeat: Infinity, ease: 'easeInOut' },
  )

  const legSwing = state === 'walk' && !reduced
  const armsUp = state === 'celebrate'

  return (
    <motion.svg
      viewBox="0 0 120 170"
      width={96 * scale}
      height={136 * scale}
      className={cn('select-none overflow-visible', className)}
      style={{ scaleX: facing === 'left' ? -1 : 1 }}
      data-testid="robot-character"
      data-robot-state={state}
      data-robot-action={action ?? ''}
    >
      <defs>
        <linearGradient id="robot-body-gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="55%" stopColor="#eef0f5" />
          <stop offset="100%" stopColor="#d7dbe6" />
        </linearGradient>
        <linearGradient id="robot-visor-gradient" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#1b1f2e" />
          <stop offset="100%" stopColor="#0a0c14" />
        </linearGradient>
        <filter id={EYE_GLOW_FILTER} x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="2.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id={EAR_GLOW_FILTER} x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="1.6" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* contact shadow — follows the body, never a separate timer */}
      <motion.ellipse
        cx={60}
        cy={162}
        rx={state === 'celebrate' ? 30 : 24}
        ry={6}
        fill="#000"
        opacity={0.16}
        animate={state === 'walk' ? { rx: [24, 20, 24] } : undefined}
        transition={bodyTransition}
      />

      <motion.g animate={bodyAnimate} transition={bodyTransition}>
        {/* legs */}
        <motion.g
          data-part="leg-left"
          animate={legSwing ? { rotate: [-18, 18, -18] } : { rotate: 0 }}
          transition={legSwing ? t({ duration: 0.5, repeat: Infinity, ease: 'easeInOut' }) : t({ duration: 0.2 })}
          style={{ transformOrigin: '46px 118px' }}
        >
          <rect x={40} y={118} width={12} height={32} rx={6} fill="url(#robot-body-gradient)" />
          <rect x={38} y={146} width={16} height={8} rx={4} fill="#c7cbd8" />
        </motion.g>
        <motion.g
          data-part="leg-right"
          animate={legSwing ? { rotate: [18, -18, 18] } : { rotate: 0 }}
          transition={legSwing ? t({ duration: 0.5, repeat: Infinity, ease: 'easeInOut' }) : t({ duration: 0.2 })}
          style={{ transformOrigin: '74px 118px' }}
        >
          <rect x={68} y={118} width={12} height={32} rx={6} fill="url(#robot-body-gradient)" />
          <rect x={66} y={146} width={16} height={8} rx={4} fill="#c7cbd8" />
        </motion.g>

        {/* torso */}
        <rect x={32} y={70} width={56} height={54} rx={18} fill="url(#robot-body-gradient)" />
        <rect x={44} y={82} width={32} height={10} rx={5} fill="#aab0c2" opacity={0.5} />

        {/* arms */}
        <motion.g
          data-part="arm-left"
          animate={
            armsUp
              ? { rotate: -150 }
              : legSwing
                ? { rotate: [12, -12, 12] }
                : state === 'shield'
                  ? { rotate: -60 }
                  : { rotate: 0 }
          }
          transition={t({ duration: legSwing ? 0.5 : 0.4, repeat: legSwing ? Infinity : 0, ease: 'easeInOut' })}
          style={{ transformOrigin: '34px 78px' }}
        >
          <rect x={18} y={78} width={12} height={30} rx={6} fill="url(#robot-body-gradient)" />
          <circle cx={24} cy={112} r={7} fill="#eef0f5" />
        </motion.g>
        <motion.g
          data-part="arm-right"
          animate={
            armsUp
              ? { rotate: 150 }
              : legSwing
                ? { rotate: [-12, 12, -12] }
                : carrying
                  ? { rotate: -70 }
                  : state === 'shield'
                    ? { rotate: 60 }
                    : { rotate: 0 }
          }
          transition={t({ duration: legSwing ? 0.5 : 0.4, repeat: legSwing ? Infinity : 0, ease: 'easeInOut' })}
          style={{ originX: '86px', originY: '78px' }}
        >
          <rect x={90} y={78} width={12} height={30} rx={6} fill="url(#robot-body-gradient)" />
          <circle cx={96} cy={112} r={7} fill="#eef0f5" />
        </motion.g>

        {carrying && (
          <g data-testid="robot-carried-box">
            <rect x={38} y={100} width={44} height={30} rx={4} fill="#c9a876" stroke="#8a6d3f" strokeWidth={1.5} />
            <line x1={38} y1={115} x2={82} y2={115} stroke="#8a6d3f" strokeWidth={1.5} />
            <text
              x={60}
              y={118}
              textAnchor="middle"
              fontSize={7}
              fill="#4a3a20"
              className="font-sans"
              style={{ pointerEvents: 'none' }}
            >
              {carrying.label.length > 14 ? carrying.label.slice(0, 12) + '…' : carrying.label}
            </text>
          </g>
        )}

        {state === 'shield' && (
          <motion.path
            d="M 96 70 L 112 78 L 112 100 Q 112 112 96 120 Q 80 112 80 100 L 80 78 Z"
            fill="rgba(139,92,246,0.22)"
            stroke="rgba(139,92,246,0.8)"
            strokeWidth={2}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={t({ duration: 0.3 })}
          />
        )}

        {/* head */}
        <motion.g
          data-part="head"
          animate={
            state === 'idle'
              ? { rotate: [0, -4, 0, 4, 0] }
              : state === 'sad'
                ? { rotate: -8 }
                : { rotate: 0 }
          }
          transition={t({ duration: 4, repeat: state === 'idle' ? Infinity : 0, ease: 'easeInOut' })}
          style={{ originX: '60px', originY: '66px' }}
        >
          <rect x={34} y={18} width={52} height={48} rx={20} fill="url(#robot-body-gradient)" />
          {/* ear rings */}
          <circle cx={30} cy={42} r={5} fill="#ffe08a" filter={`url(#${EAR_GLOW_FILTER})`} opacity={0.9} />
          <circle cx={90} cy={42} r={5} fill="#ffe08a" filter={`url(#${EAR_GLOW_FILTER})`} opacity={0.9} />
          {/* visor */}
          <rect x={42} y={34} width={36} height={20} rx={10} fill="url(#robot-visor-gradient)" />
          {/* eyes */}
          <motion.g
            animate={
              state === 'error'
                ? {}
                : { opacity: [1, 1, 0.08, 1], scaleY: [1, 1, 0.15, 1] }
            }
            transition={t({ duration: 3.2, repeat: Infinity, times: [0, 0.9, 0.95, 1] })}
            style={{ originX: '60px', originY: '44px' }}
          >
            <circle
              cx={52}
              cy={44}
              r={3.4}
              fill={state === 'error' ? '#f87171' : '#67e8f9'}
              filter={`url(#${EYE_GLOW_FILTER})`}
            />
            <circle
              cx={68}
              cy={44}
              r={3.4}
              fill={state === 'error' ? '#f87171' : '#67e8f9'}
              filter={`url(#${EYE_GLOW_FILTER})`}
            />
          </motion.g>
        </motion.g>
      </motion.g>
    </motion.svg>
  )
}
