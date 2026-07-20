/**
 * Unit tests for components/chat/editDiff.ts
 *
 * Pure-function tests (vitest node env, no component mount). Cover LCS-based
 * line diffing, CRLF normalization, the anti-O(n^2) cap fallback (including
 * the exact boundary), and the deliberate empty-string edge case.
 */
import { describe, it, expect } from 'vitest'

import { computeLineDiff } from './editDiff'

describe('computeLineDiff', () => {
  it('identical lines -> all context', () => {
    expect(computeLineDiff('a\nb', 'a\nb')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' }
    ])
  })

  it('one changed line -> adjacent removed+added', () => {
    expect(computeLineDiff('a\nold\nc', 'a\nnew\nc')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'removed', text: 'old' },
      { kind: 'added', text: 'new' },
      { kind: 'context', text: 'c' }
    ])
  })

  it('CRLF normalized before comparison', () => {
    expect(computeLineDiff('a\r\nb', 'a\nb')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' }
    ])
  })

  it('CRLF normalized even when present only on the new side', () => {
    expect(computeLineDiff('a\nb', 'a\r\nb\r\nc')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' },
      { kind: 'added', text: 'c' }
    ])
  })

  it('additions only -> old is a prefix subset of new', () => {
    expect(computeLineDiff('a\nb', 'a\nb\nc\nd')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' },
      { kind: 'added', text: 'c' },
      { kind: 'added', text: 'd' }
    ])
  })

  it('removals only -> new is a prefix subset of old', () => {
    expect(computeLineDiff('a\nb\nc\nd', 'a\nb')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'context', text: 'b' },
      { kind: 'removed', text: 'c' },
      { kind: 'removed', text: 'd' }
    ])
  })

  it('multiple change blocks interleaved with context', () => {
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

  it('empty strings -> a single empty context row (deliberate behavior)', () => {
    // ''.split('\n') === [''], so there is no "zero lines" case: an empty
    // string is treated as a single empty line, common to both sides.
    expect(computeLineDiff('', '')).toEqual([{ kind: 'context', text: '' }])
  })

  it('one side empty, the other not -> empty removed/added row, no crash', () => {
    expect(computeLineDiff('', 'a')).toEqual([
      { kind: 'removed', text: '' },
      { kind: 'added', text: 'a' }
    ])
  })

  it('beyond the line cap degrades to full removed/added blocks', () => {
    const big = Array.from({ length: 500 }, (_, i) => `r${i}`).join('\n')
    const rows = computeLineDiff(big, big + '\nx')

    // Fallback, not LCS: no context rows at all, 500 removed + 501 added.
    expect(rows.every((r) => r.kind !== 'context')).toBe(true)
    expect(rows).toHaveLength(1001)
  })

  it('exactly at the cap (400 lines) still runs the LCS -> context rows present', () => {
    const oldLines = Array.from({ length: 400 }, (_, i) => `r${i}`)
    const newLines = [...oldLines.slice(0, 399), 'CHANGED']
    const rows = computeLineDiff(oldLines.join('\n'), newLines.join('\n'))

    expect(rows.some((r) => r.kind === 'context')).toBe(true)
    expect(rows).toHaveLength(401)
    expect(rows.slice(0, 399).every((r) => r.kind === 'context')).toBe(true)
    expect(rows[399]).toEqual({ kind: 'removed', text: 'r399' })
    expect(rows[400]).toEqual({ kind: 'added', text: 'CHANGED' })
  })

  it('one line past the cap (401 lines) falls back -> no context rows at all', () => {
    const oldLines = Array.from({ length: 401 }, (_, i) => `r${i}`)
    const newLines = [...oldLines.slice(0, 400), 'CHANGED']
    const rows = computeLineDiff(oldLines.join('\n'), newLines.join('\n'))

    expect(rows.every((r) => r.kind !== 'context')).toBe(true)
    expect(rows).toHaveLength(802)
  })

  it('the cap fallback preserves order: all removed rows before all added rows', () => {
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
