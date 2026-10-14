import type { ReactNode } from 'react'
import type { GroundingReport } from '@/lib/api/types'

export interface Segment {
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

// Personal data is replaced at upload by tokens like <PERSON_c5e7f7>. They are shown as a
// short labelled tag instead of the raw token, which is hard to read mid-sentence.
// Also the previews the final privacy check writes when an answer itself contains personal
// data ("J***************m"): first and last character around three or more asterisks.
const MASK_RE = /<([A-Z][A-Z_]*?)_([0-9a-f]{6,})>|\b[A-Za-z0-9]\*{3,}[A-Za-z0-9]\b/g
const MASK_LABEL: Record<string, string> = {
  PERSON: 'person',
  EMAIL_ADDRESS: 'email',
  PHONE_NUMBER: 'phone',
  LOCATION: 'place',
  CREDIT_CARD: 'card number',
  IBAN_CODE: 'bank account',
  US_SSN: 'ID number',
}

export function withMaskedValues(text: string): ReactNode {
  if (!text.includes('<') && !text.includes('***')) return text
  const out: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(MASK_RE)) {
    const at = match.index ?? 0
    if (at > last) out.push(text.slice(last, at))
    const label = match[1] ? (MASK_LABEL[match[1]] ?? match[1].toLowerCase().replace(/_/g, ' ')) : 'hidden'
    out.push(
      <span
        key={at}
        data-testid="masked-value"
        title={
          match[1]
            ? `A ${label} from the document, hidden for privacy when it was uploaded (${match[0]}). Turn on Reveal PII to include it in answers.`
            : 'Personal data the answer contained, hidden by the final privacy check.'
        }
        className="mx-0.5 inline-flex items-center rounded-sm bg-surface px-1 align-baseline text-[0.85em] text-muted-foreground ring-1 ring-border"
      >
        {label}
      </span>,
    )
    last = at + match[0].length
  }
  if (last === 0) return text
  if (last < text.length) out.push(text.slice(last))
  return out
}

