/**
 * Unit tests for stores/permissionMode.ts (Fase 7).
 *
 * Pure Pinia store tests (vitest node env). The store keys the authorization
 * tier by conversation id, fetching the REST snapshot once via
 * ensureForConversation, folding the `permission_mode.updated` WS frame via
 * applyModeUpdated, and mutating optimistically via setMode (rolling back on
 * failure).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { usePermissionModeStore, DEFAULT_PERMISSION_MODE } from './permissionMode'
import { api } from '../services/api'
import type { PermissionModeResponse } from '../types/permission'

vi.mock('../services/api', () => ({
  api: {
    getPermissionMode: vi.fn(),
    setPermissionMode: vi.fn(),
  },
}))

const getMock = vi.mocked(api.getPermissionMode)
const setMock = vi.mocked(api.setPermissionMode)

function res(conversation_id: string, mode: PermissionModeResponse['mode']): PermissionModeResponse {
  return { conversation_id, mode }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('permissionMode store', () => {
  it('defaults to strict for an unknown conversation', () => {
    const s = usePermissionModeStore()
    expect(s.modeFor('c1')).toBe(DEFAULT_PERMISSION_MODE)
    expect(s.modeFor(null)).toBe('strict')
  })

  it('ensureForConversation fetches once', async () => {
    const s = usePermissionModeStore()
    getMock.mockResolvedValue(res('c1', 'autopilot'))
    await s.ensureForConversation('c1')
    await s.ensureForConversation('c1')
    expect(getMock).toHaveBeenCalledTimes(1)
    expect(s.modeFor('c1')).toBe('autopilot')
  })

  it('applyModeUpdated folds the pushed tier', () => {
    const s = usePermissionModeStore()
    s.applyModeUpdated({ type: 'permission_mode.updated', conversation_id: 'c1', mode: 'plan' })
    expect(s.modeFor('c1')).toBe('plan')
  })

  it('setMode is optimistic and confirms from the server response', async () => {
    const s = usePermissionModeStore()
    setMock.mockResolvedValue(res('c1', 'auto_edits'))
    await s.setMode('c1', 'auto_edits')
    expect(s.modeFor('c1')).toBe('auto_edits')
    expect(setMock).toHaveBeenCalledWith('c1', 'auto_edits')
  })

  it('setMode rolls back on failure', async () => {
    const s = usePermissionModeStore()
    s.applyModeUpdated({ type: 'permission_mode.updated', conversation_id: 'c1', mode: 'strict' })
    setMock.mockRejectedValue(new Error('boom'))
    await expect(s.setMode('c1', 'autopilot')).rejects.toThrow('boom')
    expect(s.modeFor('c1')).toBe('strict') // rolled back
  })
})
