import { Fragment, type ReactNode } from 'react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { ChatCitation, GroundingReport } from '@/lib/api/types'
import { segmentAnswer, withMaskedValues } from './answer-segments'
import { cn } from '@/lib/utils'

function withCitations(
  text: string,
  citations: ChatCitation[],
  hoveredChunk: string | null,
  onHover: (chunkId: string | null) => void,
  keyPrefix: string,
): ReactNode[] {
  return text.split(/(\[\d+(?:\s*,\s*\d+)*\])/g).map((part, i) => {
    const group = /^\[(\d+(?:\s*,\s*\d+)*)\]$/.exec(part)
    if (!group) return <Fragment key={`${keyPrefix}-${i}`}>{withMaskedValues(part)}</Fragment>
    // "[7, 8]" is two citations; each number gets its own chip.
    return (
      <Fragment key={`${keyPrefix}-${i}`}>
        {group[1].split(',').map((raw, j) => {
          const marker = Number(raw.trim())
          const citation = citations.find((c) => c.marker === marker)
          if (!citation) {
            return (
              <span
                key={j}
                className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-sm border border-dashed border-muted-foreground/40 px-1 align-text-top text-[10px] tabular-nums text-muted-foreground"
                title="This number does not point at any retrieved source."
              >
                {marker}
              </span>
            )
          }
          return (
            <button
              key={j}
              type="button"
              data-testid={`citation-marker-${citation.marker}`}
              data-chunk={citation.chunk_id}
              aria-label={`Source ${citation.marker}`}
              onMouseEnter={() => onHover(citation.chunk_id)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(citation.chunk_id)}
              onBlur={() => onHover(null)}
              className={cn(
                'mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-sm px-1 align-text-top text-[10px] font-semibold tabular-nums transition-colors duration-micro',
                hoveredChunk === citation.chunk_id ? 'bg-gold text-on-accent' : 'bg-accent/25 text-foreground hover:bg-accent/50',
              )}
            >
              {citation.marker}
            </button>
          )
        })}
      </Fragment>
    )
  })
}

/** An answer with its citation markers made interactive and any sentence the grounding check
 * could not support marked in place. */
export function AnswerText({
  content,
  citations,
  grounding,
  hoveredChunk,
  onHoverChunk,
}: {
  content: string
  citations: ChatCitation[]
  grounding?: GroundingReport | null
  hoveredChunk: string | null
  onHoverChunk: (chunkId: string | null) => void
}) {
  return (
    <>
      {segmentAnswer(content, grounding).map((segment, i) =>
        segment.unsupported ? (
          <Tooltip key={i}>
            <TooltipTrigger asChild>
              <mark
                tabIndex={0}
                data-testid="unsupported-sentence"
                className="cursor-help bg-transparent text-inherit underline decoration-danger decoration-solid decoration-2 underline-offset-4"
              >
                {withCitations(segment.text, citations, hoveredChunk, onHoverChunk, `u${i}`)}
              </mark>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">The checker found nothing in the retrieved text that supports this sentence.</TooltipContent>
          </Tooltip>
        ) : (
          <Fragment key={i}>{withCitations(segment.text, citations, hoveredChunk, onHoverChunk, `s${i}`)}</Fragment>
        ),
      )}
    </>
  )
}
