/**
 * Unit tests for components/chat/editDiff.ts
 *
 * Pure-function tests (vitest node env, no component mount). Cover LCS-based
 * line diffing, CRLF normalization, the anti-O(n^2) cap fallback, and the
 * deliberate empty-string edge case.
 */
import { describe, it, expect } from 'vitest'

import { computeLineDiff } from './editDiff'

describe('computeLineDiff', () => {
  it('righe identiche -> context', () => {
    expect(computeLineDiff('a\nb', 'a\nb')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' }
    ])
  })

  it('modifica una riga -> removed+added contigue', () => {
    expect(computeLineDiff('a\nold\nc', 'a\nnew\nc')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'removed', text: 'old' },
      { kind: 'added', text: 'new' },
      { kind: 'context', text: 'c' }
    ])
  })

  it('CRLF normalizzati prima del confronto', () => {
    expect(computeLineDiff('a\r\nb', 'a\nb')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' }
    ])
  })

  it('CRLF normalizzati anche quando presenti solo nel nuovo lato', () => {
    expect(computeLineDiff('a\nb', 'a\r\nb\r\nc')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' },
      { kind: 'added', text: 'c' }
    ])
  })

  it('solo aggiunte -> old e un sottoinsieme prefisso di new', () => {
    expect(computeLineDiff('a\nb', 'a\nb\nc\nd')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' },
      { kind: 'added', text: 'c' },
      { kind: 'added', text: 'd' }
    ])
  })

  it('solo rimozioni -> new e un sottoinsieme prefisso di old', () => {
    expect(computeLineDiff('a\nb\nc\nd', 'a\nb')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' },
      { kind: 'removed', text: 'c' },
      { kind: 'removed', text: 'd' }
    ])
  })

  it('blocchi multipli di modifica intervallati da context', () => {
    expect(computeLineDiff('a\nold1\nb\nold2\nc', 'a\nnew1\nb\nnew2\nc')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'removed', text: 'old1' },
      { kind: 'added', text: 'new1' },
      { kind: 'context', text: 'b' },
      { kind: 'removed', text: 'old2' },
      { kind: 'added', text: 'new2' },
      { kind: 'context', text: 'c' }
    ])
  })

  it('stringhe vuote -> una riga di context vuota (comportamento deliberato)', () => {
    // ''.split('\n') === [''], quindi non ci sono "zero righe": una stringa
    // vuota e' trattata come una singola riga vuota, comune a entrambi i lati.
    expect(computeLineDiff('', '')).toEqual([{ kind: 'context', text: '' }])
  })

  it('un lato vuoto e altro non vuoto -> riga vuota removed/added, non crash', () => {
    expect(computeLineDiff('', 'a')).toEqual([
      { kind: 'removed', text: '' },
      { kind: 'added', text: 'a' }
    ])
  })

  it('oltre il cap righe degrada a blocchi pieni removed/added', () => {
    const big = Array.from({ length: 500 }, (_, i) => `r${i}`).join('\n')
    const rows = computeLineDiff(big, big + '\nx')
    expect(rows.some((r) => r.kind === 'removed')).toBe(true) // fallback, non LCS
  })

  it("il fallback oltre il cap preserva l'ordine: tutte le removed prima delle added", () => {
    const bigOld = Array.from({ length: 500 }, (_, i) => `old${i}`).join('\n')
    const bigNew = Array.from({ length: 10 }, (_, i) => `new${i}`).join('\n')
    const rows = computeLineDiff(bigOld, bigNew)

    expect(rows).toHaveLength(510)
    expect(rows.slice(0, 500).every((r) => r.kind === 'removed')).toBe(true)
    expect(rows.slice(500).every((r) => r.kind === 'added')).toBe(true)
    expect(rows[0]).toEqual({ kind: 'removed', text: 'old0' })
    expect(rows[509]).toEqual({ kind: 'added', text: 'new9' })
  })
})
