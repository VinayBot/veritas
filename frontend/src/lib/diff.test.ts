import { describe, expect, it } from 'vitest'
import { diffWords, similarity } from './diff'

const join = (parts: ReturnType<typeof diffWords>, kinds: string[]) => parts.filter((p) => kinds.includes(p.kind)).map((p) => p.text).join('')

describe('diffWords', () => {
  it('reconstructs both inputs exactly', () => {
    const before = 'Employees accrue two days per month.'
    const after = 'Employees accrue two paid days each month, up to 24.'
    const parts = diffWords(before, after)
    expect(join(parts, ['same', 'removed'])).toBe(before)
    expect(join(parts, ['same', 'added'])).toBe(after)
  })

  it('marks only what changed', () => {
    const parts = diffWords('approval from a manager', 'approval from a Vice President')
    expect(parts.filter((p) => p.kind === 'removed').map((p) => p.text.trim())).toEqual(['manager'])
    expect(join(parts, ['added']).trim()).toBe('Vice President')
  })

  it('handles identical and empty text', () => {
    expect(diffWords('same text', 'same text')).toEqual([{ text: 'same text', kind: 'same' }])
    expect(diffWords('', '')).toEqual([])
    expect(diffWords('', 'new').every((p) => p.kind === 'added')).toBe(true)
  })
})

describe('similarity', () => {
  it('is 1 for identical answers and lower as they diverge', () => {
    expect(similarity('a b c', 'a b c')).toBe(1)
    expect(similarity('a b c d', 'a b x d')).toBeCloseTo(0.75)
    expect(similarity('one two', 'three four')).toBe(0)
  })
})
