import { Fragment, type ReactNode } from 'react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { ChatCitation, GroundingReport } from '@/lib/api/types'
import { cn } from '@/lib/utils'

interface Segment {
  text: string
  unsupported: boolean
}

/** Splits the answer around the sentences the grounding check found no support for. Exported
 * for tests: joining the segments must give back the answer exactly. */
export function segmentAnswer(content: string, grounding: GroundingReport | null | undefined): Segment[] {
  const flagged = (grounding?.sentences ?? []).filter((s) => !s.supported).map((s) => s.text)
  let segments: Segment[] = [{ text: content, unsupported: false }]
  for (const sentence of flagged) {
    const next: Segment[] = []
    for (const segment of segments) {
      const at = segment.unsupported ? -1 : segment.text.indexOf(sentence)
      if (at === -1) {
        next.push(segment)
        continue
      }
      if (at > 0) next.push({ text: segment.text.slice(0, at), unsupported: false })
      next.push({ text: sentence, unsupported: true })
      if (at + sentence.length < segment.text.length) next.push({ text: segment.text.slice(at + sentence.length), unsupported: false })
    }
    segments = next
  }
  return segments.filter((s) => s.text.length > 0)
}

function withCitations(
  text: string,
  citations: ChatCitation[],
  hoveredChunk: string | null,
  onHover: (chunkId: string | null) => void,
  keyPrefix: string,
): ReactNode[] {
  return text.split(/(\[\d+\])/g).map((part, i) => {
    const match = /^\[(\d+)\]$/.exec(part)
    if (!match) return <Fragment key={`${keyPrefix}-${i}`}>{part}</Fragment>
    const citation = citations.find((c) => c.marker === Number(match[1]))
    if (!citation) {
      return (
        <span key={`${keyPrefix}-${i}`} className="text-danger" title="This marker does not point at any retrieved source.">
          {part}
        </span>
      )
    }
    return (
      <button
        key={`${keyPrefix}-${i}`}
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
                className="cursor-help rounded-sm bg-danger/15 text-foreground underline decoration-danger decoration-wavy underline-offset-4"
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
