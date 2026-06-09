import { describe, it, expect } from 'vitest'
import { formatRelativeTime } from './relativeTime'

const NOW = new Date('2026-06-09T12:00:00Z').getTime()
const isoAgo = (ms: number): string => new Date(NOW - ms).toISOString()

describe('formatRelativeTime', () => {
  it('returns "adesso" under a minute', () => {
    expect(formatRelativeTime(isoAgo(30_000), NOW)).toBe('adesso')
  })
  it('returns minutes', () => {
    expect(formatRelativeTime(isoAgo(5 * 60_000), NOW)).toBe('5 min fa')
  })
  it('returns hours', () => {
    expect(formatRelativeTime(isoAgo(3 * 3_600_000), NOW)).toBe('3h fa')
  })
  it('returns "ieri" at one day', () => {
    expect(formatRelativeTime(isoAgo(25 * 3_600_000), NOW)).toBe('ieri')
  })
  it('returns days under a month', () => {
    expect(formatRelativeTime(isoAgo(5 * 86_400_000), NOW)).toBe('5g fa')
  })
})
