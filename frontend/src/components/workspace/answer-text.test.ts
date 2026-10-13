import { describe, expect, it } from 'vitest'
import { segmentAnswer } from './AnswerText'

const grounding = (flags: [string, boolean][]) => ({
  score: flags.filter(([, ok]) => ok).length / flags.length,
  supported: flags.filter(([, ok]) => ok).length,
  total: flags.length,
  sentences: flags.map(([text, supported]) => ({ text, supported })),
})

describe('segmentAnswer', () => {
  it('marks exactly the unsupported sentence and loses no text', () => {
    const answer = 'Employees accrue two days per month [1]. They also get a company car. Approval is needed [2].'
    const segments = segmentAnswer(
      answer,
      grounding([
        ['Employees accrue two days per month [1].', true],
        ['They also get a company car.', false],
        ['Approval is needed [2].', true],
      ]),
    )
    expect(segments.map((s) => s.text).join('')).toBe(answer)
    expect(segments.filter((s) => s.unsupported).map((s) => s.text)).toEqual(['They also get a company car.'])
  })

  it('returns the whole answer unmarked when grounding was not measured or found nothing', () => {
    expect(segmentAnswer('All fine.', null)).toEqual([{ text: 'All fine.', unsupported: false }])
    expect(segmentAnswer('All fine.', grounding([['All fine.', true]]))).toEqual([{ text: 'All fine.', unsupported: false }])
  })

  it('ignores a flagged sentence that is not literally in the answer', () => {
    const segments = segmentAnswer('Real text.', grounding([['Something else entirely.', false]]))
    expect(segments).toEqual([{ text: 'Real text.', unsupported: false }])
  })
})
