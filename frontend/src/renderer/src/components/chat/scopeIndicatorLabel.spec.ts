/**
 * Unit tests for components/chat/scopeIndicatorLabel.ts
 *
 * Pure-function tests (vitest node env, no component mount). They cover the
 * compact chip label (empty / single / multi) and the full-path tooltip,
 * including Windows + POSIX separators and trailing slashes.
 */
import { describe, it, expect } from 'vitest'

import { scopeChipLabel, scopeTooltip } from './scopeIndicatorLabel'

describe('scopeChipLabel', () => {
  it('returns the empty sentinel for no folders', () => {
    expect(scopeChipLabel([])).toEqual({ text: 'Nessuno scope', empty: true })
  })

  it('uses the basename for a single POSIX folder', () => {
    expect(scopeChipLabel(['C:/Users/Jays/Desktop'])).toEqual({
      text: 'Desktop',
      empty: false,
    })
  })

  it('uses the basename for a single Windows folder', () => {
    expect(scopeChipLabel(['C:\\Users\\Jays\\Documents'])).toEqual({
      text: 'Documents',
      empty: false,
    })
  })

  it('tolerates a trailing slash', () => {
    expect(scopeChipLabel(['/home/jays/projects/'])).toEqual({
      text: 'projects',
      empty: false,
    })
    expect(scopeChipLabel(['C:\\a\\b\\'])).toEqual({ text: 'b', empty: false })
  })

  it('appends a +N suffix for multiple folders', () => {
    expect(scopeChipLabel(['C:\\a\\Desktop', 'D:\\b\\Docs'])).toEqual({
      text: 'Desktop +1',
      empty: false,
    })
    expect(scopeChipLabel(['/a/one', '/b/two', '/c/three'])).toEqual({
      text: 'one +2',
      empty: false,
    })
  })
})

describe('scopeTooltip', () => {
  it('returns a friendly sentinel when empty', () => {
    expect(scopeTooltip([])).toBe('Nessuna cartella nello scope')
  })

  it('joins full paths with newlines', () => {
    expect(scopeTooltip(['C:\\a\\Desktop', 'D:\\b\\Docs'])).toBe(
      'C:\\a\\Desktop\nD:\\b\\Docs',
    )
  })

  it('returns the single full path unchanged', () => {
    expect(scopeTooltip(['/home/jays/projects'])).toBe('/home/jays/projects')
  })
})
