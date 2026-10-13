/** Word-level diff between two answers, for seeing where two strategies disagree. */
export interface DiffPart {
  text: string
  kind: 'same' | 'added' | 'removed'
}

const tokenize = (text: string) => text.match(/\S+|\s+/g) ?? []

/** Longest-common-subsequence diff from `before` to `after`. Whitespace is kept as tokens so
 * the result re-joins to exactly `after` (same + added) or `before` (same + removed). */
export function diffWords(before: string, after: string): DiffPart[] {
  const a = tokenize(before)
  const b = tokenize(after)
  const rows = a.length + 1
  const cols = b.length + 1
  const table = new Uint16Array(rows * cols)
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i * cols + j] = a[i] === b[j] ? table[(i + 1) * cols + j + 1] + 1 : Math.max(table[(i + 1) * cols + j], table[i * cols + j + 1])
    }
  }
  const parts: DiffPart[] = []
  const push = (text: string, kind: DiffPart['kind']) => {
    const last = parts[parts.length - 1]
    if (last && last.kind === kind) last.text += text
    else parts.push({ text, kind })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push(a[i], 'same')
      i += 1
      j += 1
    } else if (table[(i + 1) * cols + j] >= table[i * cols + j + 1]) {
      push(a[i], 'removed')
      i += 1
    } else {
      push(b[j], 'added')
      j += 1
    }
  }
  while (i < a.length) push(a[i++], 'removed')
  while (j < b.length) push(b[j++], 'added')
  return parts
}

/** Share of `after`'s words that also appear, in order, in `before`. 1 = identical wording. */
export function similarity(before: string, after: string): number {
  const parts = diffWords(before, after)
  const words = (kind: DiffPart['kind']) => parts.filter((p) => p.kind === kind).reduce((n, p) => n + (p.text.match(/\S+/g)?.length ?? 0), 0)
  const same = words('same')
  const total = same + Math.max(words('added'), words('removed'))
  return total === 0 ? 1 : same / total
}
