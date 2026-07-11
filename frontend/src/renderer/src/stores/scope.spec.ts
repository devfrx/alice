/**
 * Unit tests for stores/scope.ts
 *
 * Pure Pinia store tests (vitest node env, no DOM required). A fresh Pinia is
 * installed per test. The store keys workspace scope by conversation id,
 * folding the `scope.updated` events-WS frame (full folder list) via
 * applyScopeUpdated, fetching the REST snapshot once per conversation via
 * ensureForConversation, and mutating via setFolders / clear. The two
 * mutations let an `ApiError` (HTTP 409 "scope_locked") propagate.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { useScopeStore } from './scope'
import { scopeApi, ApiError } from '../services/api'
import type { ScopeResponse } from '../types/scope'

// The store imports `{ scopeApi }` from services/api; stub just the scope
// methods so fetch / ensureForConversation / setFolders / clear resolve
// without reaching a backend. A minimal `ApiError` is also exported from the
// mock so the 409 `scope_locked` conflict can be simulated and asserted on.
vi.mock('../services/api', () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      message: string
    ) {
      super(message)
      this.name = 'ApiError'
    }
  }
  return {
    ApiError,
    scopeApi: {
      getScope: vi.fn(),
      setScope: vi.fn(),
      clearScope: vi.fn()
    }
  }
})

const getScopeMock = vi.mocked(scopeApi.getScope)
const setScopeMock = vi.mocked(scopeApi.setScope)
const clearScopeMock = vi.mocked(scopeApi.clearScope)

function scopeRes(conversationId: string, folders: string[], isIdle = true): ScopeResponse {
  return { conversation_id: conversationId, folders, is_idle: isIdle }
}

beforeEach(() => {
  setActivePinia(createPinia())
  getScopeMock.mockReset()
  setScopeMock.mockReset()
  clearScopeMock.mockReset()
})

// ---------------------------------------------------------------------------
// getters
// ---------------------------------------------------------------------------

describe('getters', () => {
  it('return defaults for an unknown conversation id', () => {
    const s = useScopeStore()
    expect(s.foldersFor('nope')).toEqual([])
    expect(s.isIdleFor('nope')).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// fetch
// ---------------------------------------------------------------------------

describe('fetch', () => {
  it('populates folders and isIdle from the response is_idle', async () => {
    getScopeMock.mockResolvedValue(scopeRes('c1', ['/a', '/b'], false))
    const s = useScopeStore()

    await s.fetch('c1')

    expect(getScopeMock).toHaveBeenCalledWith('c1')
    expect(s.foldersFor('c1')).toEqual(['/a', '/b'])
    expect(s.isIdleFor('c1')).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// applyScopeUpdated (live fold)
// ---------------------------------------------------------------------------

describe('applyScopeUpdated', () => {
  it('replaces folders and defaults isIdle to true when none known', () => {
    const s = useScopeStore()
    expect(s.foldersFor('c1')).toEqual([])

    s.applyScopeUpdated({ conversation_id: 'c1', folders: ['/x'] })

    expect(s.foldersFor('c1')).toEqual(['/x'])
    expect(s.isIdleFor('c1')).toBe(true)
  })

  it('keeps the previously-known isIdle flag', async () => {
    getScopeMock.mockResolvedValue(scopeRes('c1', ['/a'], false))
    const s = useScopeStore()
    await s.fetch('c1')
    expect(s.isIdleFor('c1')).toBe(false)

    s.applyScopeUpdated({ conversation_id: 'c1', folders: ['/a', '/b'] })

    expect(s.foldersFor('c1')).toEqual(['/a', '/b'])
    expect(s.isIdleFor('c1')).toBe(false) // preserved across the fold
  })

  it('keeps conversations independent', () => {
    const s = useScopeStore()
    s.applyScopeUpdated({ conversation_id: 'c1', folders: ['/a'] })
    s.applyScopeUpdated({ conversation_id: 'c2', folders: ['/b'] })

    expect(s.foldersFor('c1')).toEqual(['/a'])
    expect(s.foldersFor('c2')).toEqual(['/b'])
  })
})

// ---------------------------------------------------------------------------
// setFolders
// ---------------------------------------------------------------------------

describe('setFolders', () => {
  it('calls api.setScope and updates the store from the response', async () => {
    setScopeMock.mockResolvedValue(scopeRes('c1', ['/a', '/b'], true))
    const s = useScopeStore()

    await s.setFolders('c1', ['/a', '/b'])

    expect(setScopeMock).toHaveBeenCalledWith('c1', ['/a', '/b'])
    expect(s.foldersFor('c1')).toEqual(['/a', '/b'])
    expect(s.isIdleFor('c1')).toBe(true)
  })

  it('propagates a thrown ApiError(409, "scope_locked") and leaves the store unchanged', async () => {
    const err = new ApiError(409, 'scope_locked')
    setScopeMock.mockRejectedValue(err)
    const s = useScopeStore()

    await expect(s.setFolders('c1', ['/a'])).rejects.toBe(err)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(409)
    expect(s.foldersFor('c1')).toEqual([]) // never mutated on failure
  })
})

// ---------------------------------------------------------------------------
// clear
// ---------------------------------------------------------------------------

describe('clear', () => {
  it('calls api.clearScope and empties the folders', async () => {
    setScopeMock.mockResolvedValue(scopeRes('c1', ['/a'], true))
    clearScopeMock.mockResolvedValue(scopeRes('c1', [], true))
    const s = useScopeStore()
    await s.setFolders('c1', ['/a'])
    expect(s.foldersFor('c1')).toEqual(['/a'])

    await s.clear('c1')

    expect(clearScopeMock).toHaveBeenCalledWith('c1')
    expect(s.foldersFor('c1')).toEqual([])
    expect(s.isIdleFor('c1')).toBe(true)
  })

  it('propagates a thrown ApiError(409)', async () => {
    const err = new ApiError(409, 'scope_locked')
    clearScopeMock.mockRejectedValue(err)
    const s = useScopeStore()

    await expect(s.clear('c1')).rejects.toBe(err)
  })
})

// ---------------------------------------------------------------------------
// ensureForConversation (fetch-once)
// ---------------------------------------------------------------------------

describe('ensureForConversation', () => {
  it('calls api.getScope once and dedupes on the second call', async () => {
    getScopeMock.mockResolvedValue(scopeRes('c1', ['/a'], true))
    const s = useScopeStore()

    await s.ensureForConversation('c1')
    expect(getScopeMock).toHaveBeenCalledTimes(1)
    expect(getScopeMock).toHaveBeenCalledWith('c1')
    expect(s.foldersFor('c1')).toEqual(['/a'])

    await s.ensureForConversation('c1')
    expect(getScopeMock).toHaveBeenCalledTimes(1) // deduped — no second fetch
  })

  it('rolls back the dedup guard on failure so a retry re-fetches', async () => {
    getScopeMock.mockRejectedValueOnce(new Error('boom'))
    const s = useScopeStore()

    await expect(s.ensureForConversation('c1')).rejects.toThrow('boom')
    expect(getScopeMock).toHaveBeenCalledTimes(1)

    getScopeMock.mockResolvedValueOnce(scopeRes('c1', ['/a'], true))
    await s.ensureForConversation('c1')
    expect(getScopeMock).toHaveBeenCalledTimes(2)
    expect(s.foldersFor('c1')).toEqual(['/a'])
  })
})

// ---------------------------------------------------------------------------
// reset
// ---------------------------------------------------------------------------

describe('reset', () => {
  it('clears all cached scopes and the fetched-once guard', async () => {
    getScopeMock.mockResolvedValue(scopeRes('c1', ['/a'], true))
    const s = useScopeStore()
    await s.ensureForConversation('c1')
    expect(s.foldersFor('c1')).toEqual(['/a'])

    s.reset()
    expect(s.foldersFor('c1')).toEqual([])

    // Guard cleared too: ensureForConversation fetches again after reset.
    await s.ensureForConversation('c1')
    expect(getScopeMock).toHaveBeenCalledTimes(2)
  })
})
