/**
 * Unit tests for stores/memory.ts (vitest node env, no DOM).
 *
 * The store wraps the /api/memory endpoints: list (entries+total), semantic
 * search, per-id delete, session/all clear and stats, normalising every
 * failure into the `error` ref (it never throws).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { useMemoryStore } from './memory'
import { memoryApi } from '../services/api'
import type { MemoryEntry, MemoryStats } from '../types/memory'

vi.mock('../services/api', () => ({
  memoryApi: {
    getMemories: vi.fn(),
    searchMemories: vi.fn(),
    deleteMemory: vi.fn(),
    clearSessionMemory: vi.fn(),
    clearAllMemory: vi.fn(),
    getMemoryStats: vi.fn()
  }
}))

const getMemoriesMock = vi.mocked(memoryApi.getMemories)
const searchMock = vi.mocked(memoryApi.searchMemories)
const deleteMock = vi.mocked(memoryApi.deleteMemory)
const clearSessionMock = vi.mocked(memoryApi.clearSessionMemory)
const clearAllMock = vi.mocked(memoryApi.clearAllMemory)
const statsMock = vi.mocked(memoryApi.getMemoryStats)

function entry(id: string, scope = 'long_term'): MemoryEntry {
  return { id, scope, content: `memory ${id}` }
}

function stats(total: number): MemoryStats {
  return { total, by_category: {}, by_scope: {}, db_size_bytes: 0 }
}

beforeEach(() => {
  setActivePinia(createPinia())
  getMemoriesMock.mockReset()
  searchMock.mockReset()
  deleteMock.mockReset()
  clearSessionMock.mockReset()
  clearAllMock.mockReset()
  statsMock.mockReset()
})

describe('loadMemories', () => {
  it('fills entries and total from the list response', async () => {
    getMemoriesMock.mockResolvedValue({ items: [entry('a'), entry('b')], total: 2 })
    const s = useMemoryStore()
    await s.loadMemories()
    expect(s.entries.map((e) => e.id)).toEqual(['a', 'b'])
    expect(s.total).toBe(2)
    expect(s.loading).toBe(false)
    expect(s.error).toBeNull()
  })

  it('captures failures into error without throwing', async () => {
    getMemoriesMock.mockRejectedValue(new Error('boom'))
    const s = useMemoryStore()
    await s.loadMemories()
    expect(s.error).toBe('boom')
    expect(s.loading).toBe(false)
    expect(s.entries).toEqual([])
  })
})

describe('deleteMemory', () => {
  it('removes the entry locally and decrements total', async () => {
    getMemoriesMock.mockResolvedValue({ items: [entry('a'), entry('b')], total: 2 })
    deleteMock.mockResolvedValue({ deleted: true })
    const s = useMemoryStore()
    await s.loadMemories()
    await s.deleteMemory('a')
    expect(deleteMock).toHaveBeenCalledWith('a')
    expect(s.entries.map((e) => e.id)).toEqual(['b'])
    expect(s.total).toBe(1)
  })

  it('captures delete failures into error and keeps the entry', async () => {
    getMemoriesMock.mockResolvedValue({ items: [entry('a')], total: 1 })
    deleteMock.mockRejectedValue(new Error('nope'))
    const s = useMemoryStore()
    await s.loadMemories()
    await s.deleteMemory('a')
    expect(s.error).toBe('nope')
    expect(s.entries.map((e) => e.id)).toEqual(['a'])
    expect(s.total).toBe(1)
  })
})

describe('clearSessionMemory', () => {
  it('drops session-scoped entries and subtracts deleted_count', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [entry('a', 'session'), entry('b', 'long_term')],
      total: 2
    })
    clearSessionMock.mockResolvedValue({ deleted_count: 1 })
    const s = useMemoryStore()
    await s.loadMemories()
    await s.clearSessionMemory()
    expect(s.entries.map((e) => e.id)).toEqual(['b'])
    expect(s.total).toBe(1)
  })
})

describe('clearAllMemory / search / stats', () => {
  it('clearAllMemory empties everything', async () => {
    getMemoriesMock.mockResolvedValue({ items: [entry('a')], total: 1 })
    clearAllMock.mockResolvedValue({ deleted_count: 1 })
    const s = useMemoryStore()
    await s.loadMemories()
    await s.clearAllMemory()
    expect(s.entries).toEqual([])
    expect(s.total).toBe(0)
  })

  it('searchMemories fills searchResults and clearSearchResults empties them', async () => {
    searchMock.mockResolvedValue({ results: [{ entry: entry('a'), score: 0.9 }] })
    const s = useMemoryStore()
    await s.searchMemories('query')
    expect(searchMock).toHaveBeenCalledWith('query', 10, undefined)
    expect(s.searchResults).toHaveLength(1)
    expect(s.searchResults[0].score).toBe(0.9)
    s.clearSearchResults()
    expect(s.searchResults).toEqual([])
  })

  it('loadStats stores the stats payload', async () => {
    statsMock.mockResolvedValue(stats(5))
    const s = useMemoryStore()
    await s.loadStats()
    expect(s.stats).toEqual(stats(5))
  })

  it('search failures land in error and leave results empty', async () => {
    searchMock.mockRejectedValue(new Error('down'))
    const s = useMemoryStore()
    await s.searchMemories('query')
    expect(s.error).toBe('down')
    expect(s.searchResults).toEqual([])
  })
})
