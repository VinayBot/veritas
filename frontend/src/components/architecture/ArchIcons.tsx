import type { SVGProps } from 'react'

/**
 * Original, hand-drawn icon set for the Architecture System Design diagram (AR-4). One
 * consistent duotone family: a darker fill (`DEEP`) for the icon's base shape and a lighter
 * highlight (`LIGHT`) for its top/front face, so every icon reads as the same flat/isometric
 * style at a glance. Indexes get a green variant, council a blue variant, matching the
 * brief's "Shards = green, Replicas = blue" convention. None of these trace or embed any
 * reference image (G12) — every path below is drawn from scratch.
 */

const INDIGO_DEEP = '#4B3FD6'
const INDIGO_LIGHT = '#6C63FF'
const INDIGO_HILITE = '#A9A3FF'
const GREEN_DEEP = '#1E9E73'
const GREEN_LIGHT = '#7BE0B8'
const BLUE_DEEP = '#3A3AC2'
const BLUE_LIGHT = '#5B5BD6'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Base({ size = 60, viewBox = '0 0 60 60', children, ...rest }: IconProps & { viewBox?: string }) {
  return (
    <svg width={size} height={size} viewBox={viewBox} fill="none" aria-hidden="true" {...rest}>
      {children}
    </svg>
  )
}

export function UserIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="30" cy="22" r="12" fill={INDIGO_LIGHT} />
      <circle cx="30" cy="22" r="12" fill={INDIGO_HILITE} opacity="0.35" />
      <path d="M10 52c2-11 10-17 20-17s18 6 20 17" stroke={INDIGO_DEEP} strokeWidth="5" strokeLinecap="round" fill="none" />
    </Base>
  )
}

export function GatewayIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="12" y="14" width="36" height="32" rx="6" fill={INDIGO_DEEP} />
      <rect x="12" y="14" width="36" height="12" rx="6" fill={INDIGO_LIGHT} />
      <circle cx="20" cy="20" r="2.4" fill={INDIGO_HILITE} />
      <circle cx="27" cy="20" r="2.4" fill={INDIGO_HILITE} />
      <path d="M18 34h24M18 40h16" stroke={INDIGO_HILITE} strokeWidth="3" strokeLinecap="round" />
    </Base>
  )
}

export function GuardrailsIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M30 8 48 15v14c0 13-8 20-18 23-10-3-18-10-18-23V15z" fill={INDIGO_DEEP} />
      <path d="M30 8 48 15v14c0 13-8 20-18 23z" fill={INDIGO_LIGHT} opacity="0.55" />
      <path d="M22 29l6 6 11-12" stroke={INDIGO_HILITE} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </Base>
  )
}

export function RouterIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="10" y="24" width="40" height="16" rx="4" fill={INDIGO_DEEP} />
      <rect x="10" y="24" width="40" height="6" rx="3" fill={INDIGO_LIGHT} />
      <circle cx="18" cy="32" r="2.2" fill={GREEN_LIGHT} />
      <circle cx="26" cy="32" r="2.2" fill={INDIGO_HILITE} />
      <path d="M20 24V15M30 24V12M40 24v9" stroke={INDIGO_DEEP} strokeWidth="3" strokeLinecap="round" />
      <path d="M20 15h-6M30 12h8l-3-3m3 3-3 3M40 15h4" stroke={INDIGO_LIGHT} strokeWidth="2.5" strokeLinecap="round" fill="none" />
    </Base>
  )
}

export function OrchestratorIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="9" y="12" width="42" height="36" rx="5" fill={INDIGO_DEEP} />
      <rect x="9" y="12" width="42" height="10" rx="5" fill={INDIGO_LIGHT} />
      {[0, 1, 2].map((row) =>
        [0, 1, 2, 3].map((col) => (
          <rect
            key={`${row}-${col}`}
            x={14 + col * 9}
            y={26 + row * 7}
            width="6"
            height="4"
            rx="1"
            fill={row === 1 && col === 1 ? GREEN_LIGHT : INDIGO_HILITE}
            opacity={row === 1 && col === 1 ? 1 : 0.6}
          />
        )),
      )}
    </Base>
  )
}

export function EventBusIcon(props: IconProps) {
  return (
    <Base {...props}>
      <ellipse cx="30" cy="18" rx="18" ry="7" fill={INDIGO_LIGHT} />
      <path d="M12 18v12c0 4 8 7 18 7s18-3 18-7V18" fill={INDIGO_DEEP} />
      <ellipse cx="30" cy="30" rx="18" ry="7" fill={INDIGO_LIGHT} opacity="0.5" />
      <path d="M12 30v12c0 4 8 7 18 7s18-3 18-7V30" fill={INDIGO_DEEP} opacity="0.85" />
    </Base>
  )
}

export function LlmProviderIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path
        d="M18 38c-6 0-10-4-10-9 0-4 3-8 7-9 1-6 6-10 13-10 6 0 11 4 12 9 5 1 9 5 9 10 0 5-4 9-10 9z"
        fill={INDIGO_LIGHT}
      />
      <path
        d="M18 38c-6 0-10-4-10-9 0-4 3-8 7-9 1-6 6-10 13-10 6 0 11 4 12 9"
        fill={INDIGO_HILITE}
        opacity="0.4"
      />
      <circle cx="22" cy="32" r="2.6" fill={INDIGO_DEEP} />
      <circle cx="30" cy="34" r="2.6" fill={INDIGO_DEEP} />
      <circle cx="38" cy="32" r="2.6" fill={INDIGO_DEEP} />
    </Base>
  )
}

export function IndexManagerIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="14" y="10" width="32" height="40" rx="4" fill={INDIGO_DEEP} />
      <rect x="14" y="10" width="32" height="10" rx="4" fill={INDIGO_LIGHT} />
      <rect x="19" y="26" width="22" height="4" rx="2" fill={INDIGO_HILITE} />
      <rect x="19" y="34" width="16" height="4" rx="2" fill={INDIGO_HILITE} opacity="0.7" />
      <rect x="19" y="42" width="10" height="4" rx="2" fill={INDIGO_HILITE} opacity="0.5" />
    </Base>
  )
}

function Cylinder({ fillDeep, fillLight }: { fillDeep: string; fillLight: string }) {
  return (
    <>
      <path d="M14 18c0-4 7-7 16-7s16 3 16 7v24c0 4-7 7-16 7s-16-3-16-7z" fill={fillDeep} />
      <ellipse cx="30" cy="18" rx="16" ry="7" fill={fillLight} />
    </>
  )
}

export function IndexDenseIcon(props: IconProps) {
  return (
    <Base {...props}>
      <Cylinder fillDeep={GREEN_DEEP} fillLight={GREEN_LIGHT} />
      <circle cx="24" cy="30" r="2" fill="#ffffff" opacity="0.8" />
      <circle cx="32" cy="34" r="2" fill="#ffffff" opacity="0.8" />
      <circle cx="28" cy="40" r="2" fill="#ffffff" opacity="0.8" />
    </Base>
  )
}

export function IndexSparseIcon(props: IconProps) {
  return (
    <Base {...props}>
      <Cylinder fillDeep={GREEN_DEEP} fillLight={GREEN_LIGHT} />
      <path d="M20 28h20M20 34h14M20 40h18" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" opacity="0.85" />
    </Base>
  )
}

export function IndexGraphIcon(props: IconProps) {
  return (
    <Base {...props}>
      <Cylinder fillDeep={GREEN_DEEP} fillLight={GREEN_LIGHT} />
      <circle cx="23" cy="30" r="2.4" fill="#ffffff" />
      <circle cx="34" cy="33" r="2.4" fill="#ffffff" />
      <circle cx="26" cy="41" r="2.4" fill="#ffffff" />
      <path d="M23 30 34 33M34 33 26 41M23 30 26 41" stroke="#ffffff" strokeWidth="1.5" opacity="0.8" />
    </Base>
  )
}

export function MetaDbIcon(props: IconProps) {
  return (
    <Base {...props}>
      <Cylinder fillDeep={INDIGO_DEEP} fillLight={INDIGO_LIGHT} />
      <ellipse cx="30" cy="30" rx="16" ry="6" fill="none" stroke={INDIGO_HILITE} strokeWidth="1.6" opacity="0.6" />
    </Base>
  )
}

export function CacheIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="12" y="20" width="36" height="22" rx="6" fill={INDIGO_DEEP} />
      <rect x="12" y="20" width="36" height="8" rx="4" fill={INDIGO_LIGHT} />
      <path d="M24 12l6-5 6 5" stroke={INDIGO_HILITE} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <circle cx="30" cy="32" r="4" fill={INDIGO_HILITE} />
    </Base>
  )
}

export function PiiVaultIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="13" y="24" width="34" height="26" rx="4" fill={INDIGO_DEEP} />
      <path d="M20 24v-6a10 10 0 0 1 20 0v6" stroke={INDIGO_LIGHT} strokeWidth="5" fill="none" />
      <circle cx="30" cy="36" r="5" fill={INDIGO_HILITE} />
      <rect x="28" y="38" width="4" height="7" rx="1.5" fill={INDIGO_HILITE} />
    </Base>
  )
}

export function TraceIdIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="10" y="16" width="40" height="28" rx="5" fill={INDIGO_DEEP} />
      <rect x="15" y="22" width="2.4" height="16" fill={INDIGO_HILITE} />
      <rect x="19.5" y="22" width="1.2" height="16" fill={INDIGO_HILITE} opacity="0.6" />
      <rect x="23" y="22" width="3.2" height="16" fill={INDIGO_HILITE} />
      <rect x="28.5" y="22" width="1.6" height="16" fill={INDIGO_HILITE} opacity="0.6" />
      <rect x="32" y="22" width="2.4" height="16" fill={INDIGO_HILITE} />
      <rect x="36.5" y="22" width="3.2" height="16" fill={INDIGO_HILITE} opacity="0.6" />
      <rect x="41.5" y="22" width="1.6" height="16" fill={INDIGO_HILITE} />
    </Base>
  )
}

export function IngestSchedulerIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="30" cy="30" r="19" fill={INDIGO_DEEP} />
      <circle cx="30" cy="30" r="19" fill={INDIGO_LIGHT} opacity="0.3" />
      <path d="M30 18v12l9 6" stroke={INDIGO_HILITE} strokeWidth="4" strokeLinecap="round" fill="none" />
    </Base>
  )
}

export function EvaluatorIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M20 10h20l4 8-14 32L16 18z" fill={INDIGO_DEEP} />
      <path d="M20 10h20l4 8H16z" fill={INDIGO_LIGHT} />
      <path d="M24 18l6 24 6-24" stroke={INDIGO_HILITE} strokeWidth="2" opacity="0.7" fill="none" />
    </Base>
  )
}

function CouncilMember({ hat }: { hat: boolean }) {
  return (
    <>
      <Cylinder fillDeep={BLUE_DEEP} fillLight={BLUE_LIGHT} />
      <circle cx="30" cy="28" r="7" fill="#ffffff" opacity="0.9" />
      {hat && <path d="M23 25l7-5 7 5" stroke="#ffffff" strokeWidth="2.4" fill="none" strokeLinecap="round" />}
    </>
  )
}

export function CouncilMemberIcon(props: IconProps) {
  return (
    <Base {...props}>
      <CouncilMember hat={false} />
    </Base>
  )
}

export function CouncilChairmanIcon(props: IconProps) {
  return (
    <Base {...props}>
      <CouncilMember hat />
    </Base>
  )
}

export function WorkerDoclingIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="14" y="8" width="26" height="34" rx="3" fill={INDIGO_LIGHT} />
      <path d="M40 8v34H14z" fill={INDIGO_DEEP} opacity="0.25" />
      <path d="M20 16h14M20 22h14M20 28h10" stroke={INDIGO_DEEP} strokeWidth="2.4" strokeLinecap="round" />
      <path d="M34 44l6 6-6 6" stroke={INDIGO_HILITE} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </Base>
  )
}

export function WorkerScraperIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="24" cy="24" r="13" fill="none" stroke={INDIGO_LIGHT} strokeWidth="5" />
      <path d="M33 33l12 12" stroke={INDIGO_DEEP} strokeWidth="6" strokeLinecap="round" />
      <path d="M19 24a5 5 0 0 1 5-5" stroke={INDIGO_HILITE} strokeWidth="2.4" strokeLinecap="round" fill="none" />
    </Base>
  )
}

export function WorkerRefinerIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M30 8l20 11v22L30 52 10 41V19z" fill={INDIGO_DEEP} />
      <path d="M30 8l20 11-20 11-20-11z" fill={INDIGO_LIGHT} />
      <path d="M30 30v22" stroke={INDIGO_HILITE} strokeWidth="2" opacity="0.6" />
    </Base>
  )
}

export const ARCH_ICON_BY_NODE: Record<string, (props: IconProps) => React.JSX.Element> = {
  user: UserIcon,
  gateway: GatewayIcon,
  guardrails_in: GuardrailsIcon,
  router: RouterIcon,
  orchestrator: OrchestratorIcon,
  event_bus: EventBusIcon,
  llm_providers: LlmProviderIcon,
  index_manager: IndexManagerIcon,
  index_dense: IndexDenseIcon,
  index_sparse: IndexSparseIcon,
  index_graph: IndexGraphIcon,
  metadb: MetaDbIcon,
  cache: CacheIcon,
  pii_vault: PiiVaultIcon,
  trace_ids: TraceIdIcon,
  ingest_scheduler: IngestSchedulerIcon,
  evaluator: EvaluatorIcon,
  council_member_1: CouncilMemberIcon,
  council_member_2: CouncilMemberIcon,
  council_chairman: CouncilChairmanIcon,
  worker_docling: WorkerDoclingIcon,
  worker_scraper: WorkerScraperIcon,
  worker_refiner: WorkerRefinerIcon,
}
