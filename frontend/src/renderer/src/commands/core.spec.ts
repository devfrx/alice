/**
 * Core-commands tests: registration metadata + navigation handlers.
 * Store-backed handlers are exercised with a fresh Pinia and mocked API.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { Router } from 'vue-router'
import { commandRegistry } from './registry'
import { installCoreCommands, SWITCHABLE_VIEWS } from './core'
import { chatApi } from '../services/api'

vi.mock('../services/api', () => ({
  chatApi: {
    getConversations: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    createConversation: vi.fn().mockResolvedValue({ created_at: '', updated_at: '' }),
    getConversation: vi.fn().mockResolvedValue({
      id: 'c1',
      title: null,
      created_at: '',
      updated_at: '',
      messages: []
    })
  },
  resolveBackendUrl: (p: string) => p
}))

function fakeRouter(routeName = 'assistant'): Router {
  return {
    push: vi.fn().mockResolvedValue(undefined),
    currentRoute: { value: { name: routeName } }
  } as unknown as Router
}

beforeEach(() => {
  setActivePinia(createPinia())
  commandRegistry.clear()
})

describe('installCoreCommands', () => {
  it('registers the Fase 6 core set with the spec §7 capability tags', () => {
    installCoreCommands(fakeRouter())
    const byName = new Map(commandRegistry.list().map((d) => [d.name, d]))
    expect([...byName.keys()].sort()).toEqual([
      'artifact.show',
      'conversation.new',
      'conversation.open',
      'sidebar.toggle',
      'view.switch'
    ])
    expect(byName.get('view.switch')?.capability).toBe('navigation')
    expect(byName.get('conversation.new')?.capability).toBe('mutate')
  })

  it('exposes exactly the Fase 7 agent-callable core set', () => {
    installCoreCommands(fakeRouter())
    const exposed = commandRegistry
      .list()
      .filter((d) => d.exposeToAgent === true)
      .map((d) => d.name)
      .sort()
    expect(exposed).toEqual([
      'artifact.show',
      'conversation.new',
      'conversation.open',
      'view.switch'
    ])
  })

  it('every exposed command carries a machine-facing description', () => {
    installCoreCommands(fakeRouter())
    for (const def of commandRegistry.list()) {
      if (def.exposeToAgent === true) {
        expect(def.description, `${def.name} needs a description`).toBeTruthy()
      }
    }
  })

  it('keeps sidebar.toggle UI-only (never agent-callable)', () => {
    installCoreCommands(fakeRouter())
    const def = commandRegistry.list().find((d) => d.name === 'sidebar.toggle')
    expect(def?.exposeToAgent ?? false).toBe(false)
  })

  it('view.switch pushes the named route and rejects unknown views', async () => {
    const router = fakeRouter()
    installCoreCommands(router)
    await commandRegistry.execute('view.switch', { view: 'settings' })
    expect(router.push).toHaveBeenCalledWith({ name: 'settings' })
    await expect(commandRegistry.execute('view.switch', { view: 'not-a-view' })).rejects.toThrow(
      /Unknown view/
    )
  })

  it('every SWITCHABLE_VIEWS entry is accepted', async () => {
    const router = fakeRouter()
    installCoreCommands(router)
    for (const view of SWITCHABLE_VIEWS) {
      await commandRegistry.execute('view.switch', { view })
    }
    expect(router.push).toHaveBeenCalledTimes(SWITCHABLE_VIEWS.length)
  })

  it('artifact.show routes to the board with the artifact query', async () => {
    const router = fakeRouter()
    installCoreCommands(router)
    await commandRegistry.execute('artifact.show', { artifact_id: 'a1' })
    expect(router.push).toHaveBeenCalledWith({ name: 'board', query: { artifact: 'a1' } })
  })

  it('conversation.open loads the conversation, then lands on the active chat surface', async () => {
    const router = fakeRouter('settings')
    installCoreCommands(router)
    await commandRegistry.execute('conversation.open', { conversation_id: 'c1' })
    expect(vi.mocked(chatApi.getConversation)).toHaveBeenCalledWith('c1', expect.anything())
    // ui.mode defaults to 'workspace' (no localStorage in the node test env).
    expect(router.push).toHaveBeenCalledWith({ name: 'workspace' })
  })

  it('conversation.open stays put when already on a chat surface', async () => {
    const router = fakeRouter('assistant')
    installCoreCommands(router)
    await commandRegistry.execute('conversation.open', { conversation_id: 'c1' })
    expect(router.push).not.toHaveBeenCalled()
  })

  it('conversation.open does NOT navigate when the load fails', async () => {
    const router = fakeRouter('settings')
    installCoreCommands(router)
    vi.mocked(chatApi.getConversation).mockRejectedValueOnce(new Error('404'))
    await expect(
      commandRegistry.execute('conversation.open', { conversation_id: 'missing' })
    ).rejects.toThrow('404')
    expect(router.push).not.toHaveBeenCalled()
  })

  it('re-installing replaces the core set without throwing (HMR idempotency)', () => {
    const first = fakeRouter()
    const second = fakeRouter()
    installCoreCommands(first)
    expect(() => installCoreCommands(second)).not.toThrow()
    expect(commandRegistry.list()).toHaveLength(5)
  })
})
