/**
 * Unit tests for stores/planDocument.ts
 *
 * Pure Pinia store tests (vitest node env, no DOM required). A fresh Pinia is
 * installed per test. The store keys a plan *document* by conversation id,
 * folding the `plan_document.updated` events-WS frame (full document) via
 * applyPlanDocumentUpdated and fetching the REST snapshot once per conversation
 * via ensureForConversation. An empty body means "no document".
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { usePlanDocumentStore } from './planDocument'
import { api } from '../services/api'
import type { WsPlanDocumentUpdatedMessage } from '../types/planDocument'

// The store imports `{ api }` from services/api; stub just the getPlanDocument
// method so ensureForConversation/fetch resolve without reaching a backend.
vi.mock('../services/api', () => ({
  api: {
    getPlanDocument: vi.fn(),
  },
}))

const getPlanDocumentMock = vi.mocked(api.getPlanDocument)

function updated(
  conversationId: string,
  body: string,
  title = 'Piano',
  updated_at: string | null = '2026-06-09T10:30:00Z',
): WsPlanDocumentUpdatedMessage {
  return { type: 'plan_document.updated', conversation_id: conversationId, title, body, updated_at }
}

beforeEach(() => {
  setActivePinia(createPinia())
  getPlanDocumentMock.mockReset()
})

// ---------------------------------------------------------------------------
// documentFor
// ---------------------------------------------------------------------------

describe('documentFor', () => {
  it('returns null for an unknown conversation id', () => {
    const s = usePlanDocumentStore()
    expect(s.documentFor('nope')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// fetch / ensureForConversation (REST snapshot)
// ---------------------------------------------------------------------------

describe('fetch', () => {
  it('populates documentFor from the REST snapshot', async () => {
    getPlanDocumentMock.mockResolvedValue({
      conversation_id: 'c1',
      title: 'Piano di rilascio',
      body: '# Step 1\nFare la cosa',
      updated_at: '2026-06-09T10:30:00Z',
    })
    const s = usePlanDocumentStore()

    await s.fetch('c1')

    expect(getPlanDocumentMock).toHaveBeenCalledWith('c1')
    expect(s.documentFor('c1')).toEqual({
      title: 'Piano di rilascio',
      body: '# Step 1\nFare la cosa',
      updatedAt: '2026-06-09T10:30:00Z',
    })
  })

  it('treats an empty body as no document (documentFor === null)', async () => {
    getPlanDocumentMock.mockResolvedValue({
      conversation_id: 'c1',
      title: '',
      body: '',
      updated_at: null,
    })
    const s = usePlanDocumentStore()

    await s.fetch('c1')

    expect(s.documentFor('c1')).toBeNull()
  })
})

describe('ensureForConversation', () => {
  it('calls api.getPlanDocument once and dedupes on the second call', async () => {
    getPlanDocumentMock.mockResolvedValue({
      conversation_id: 'c1',
      title: 'Piano',
      body: 'corpo',
      updated_at: null,
    })
    const s = usePlanDocumentStore()

    await s.ensureForConversation('c1')
    expect(getPlanDocumentMock).toHaveBeenCalledTimes(1)
    expect(s.documentFor('c1')?.body).toBe('corpo')

    await s.ensureForConversation('c1')
    expect(getPlanDocumentMock).toHaveBeenCalledTimes(1) // deduped — no second fetch
  })

  it('rolls back the dedup guard on failure so a retry re-fetches', async () => {
    getPlanDocumentMock.mockRejectedValueOnce(new Error('boom'))
    const s = usePlanDocumentStore()

    await expect(s.ensureForConversation('c1')).rejects.toThrow('boom')
    expect(getPlanDocumentMock).toHaveBeenCalledTimes(1)

    getPlanDocumentMock.mockResolvedValueOnce({
      conversation_id: 'c1',
      title: 'Piano',
      body: 'corpo',
      updated_at: null,
    })
    await s.ensureForConversation('c1')
    expect(getPlanDocumentMock).toHaveBeenCalledTimes(2)
    expect(s.documentFor('c1')?.body).toBe('corpo')
  })
})

// ---------------------------------------------------------------------------
// applyPlanDocumentUpdated (live fold)
// ---------------------------------------------------------------------------

describe('applyPlanDocumentUpdated', () => {
  it('folds the pushed document into documentFor(id)', () => {
    const s = usePlanDocumentStore()
    expect(s.documentFor('c1')).toBeNull()

    s.applyPlanDocumentUpdated(updated('c1', '## Piano\nUno', 'Titolo', '2026-06-09T11:00:00Z'))

    expect(s.documentFor('c1')).toEqual({
      title: 'Titolo',
      body: '## Piano\nUno',
      updatedAt: '2026-06-09T11:00:00Z',
    })
  })

  it('replaces the prior document on a second update', () => {
    const s = usePlanDocumentStore()
    s.applyPlanDocumentUpdated(updated('c1', 'vecchio'))
    s.applyPlanDocumentUpdated(updated('c1', 'nuovo', 'Nuovo titolo', null))

    expect(s.documentFor('c1')).toEqual({
      title: 'Nuovo titolo',
      body: 'nuovo',
      updatedAt: null,
    })
  })

  it('deletes the entry when the pushed body is empty (documentFor === null)', () => {
    const s = usePlanDocumentStore()
    s.applyPlanDocumentUpdated(updated('c1', 'qualcosa'))
    expect(s.documentFor('c1')).not.toBeNull()

    s.applyPlanDocumentUpdated(updated('c1', ''))
    expect(s.documentFor('c1')).toBeNull()
  })

  it('keeps conversations independent', () => {
    const s = usePlanDocumentStore()
    s.applyPlanDocumentUpdated(updated('c1', 'uno'))
    s.applyPlanDocumentUpdated(updated('c2', 'due'))

    expect(s.documentFor('c1')?.body).toBe('uno')
    expect(s.documentFor('c2')?.body).toBe('due')
  })
})

// ---------------------------------------------------------------------------
// reset
// ---------------------------------------------------------------------------

describe('reset', () => {
  it('clears all cached documents and the fetched-once guard', async () => {
    getPlanDocumentMock.mockResolvedValue({
      conversation_id: 'c1',
      title: 'Piano',
      body: 'corpo',
      updated_at: null,
    })
    const s = usePlanDocumentStore()
    await s.ensureForConversation('c1')
    expect(s.documentFor('c1')).not.toBeNull()

    s.reset()
    expect(s.documentFor('c1')).toBeNull()

    // Guard cleared too: ensureForConversation fetches again after reset.
    await s.ensureForConversation('c1')
    expect(getPlanDocumentMock).toHaveBeenCalledTimes(2)
  })
})
