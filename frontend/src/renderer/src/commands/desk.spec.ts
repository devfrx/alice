import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { Router } from 'vue-router'
import { commandRegistry } from './registry'
import { installDeskCommands, DESK_COMMAND_NAMES } from './desk'
import { useDeskStore } from '../stores/desk'

vi.stubGlobal('localStorage', {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {}
})

function fakeRouter(currentName: string): Router {
  return {
    push: vi.fn().mockResolvedValue(undefined),
    currentRoute: { value: { name: currentName } }
  } as unknown as Router
}

beforeEach(() => {
  setActivePinia(createPinia())
  commandRegistry.clear()
})

describe('installDeskCommands', () => {
  it('registers every window.* command with the expected capability', () => {
    installDeskCommands(fakeRouter('assistant'))
    const byName = new Map(commandRegistry.list().map((c) => [c.name, c]))
    expect([...byName.keys()].sort()).toEqual([...DESK_COMMAND_NAMES].sort())
    expect(byName.get('window.open')?.capability).toBe('navigation')
    expect(byName.get('window.focus')?.capability).toBe('navigation')
    expect(byName.get('window.arrange')?.capability).toBe('navigation')
    expect(byName.get('window.list')?.capability).toBe('read')
    expect(byName.get('window.close')?.capability).toBe('mutate')
    for (const c of byName.values()) expect(c.exposeToAgent).toBe(true)
  })

  it('is idempotent (HMR re-install)', () => {
    const r = fakeRouter('assistant')
    installDeskCommands(r)
    expect(() => installDeskCommands(r)).not.toThrow()
  })

  it('window.open creates a window and navigates to assistant when elsewhere', async () => {
    const router = fakeRouter('workspace')
    installDeskCommands(router)
    const result = (await commandRegistry.execute('window.open', { module: 'chart' })) as {
      window_id: string
    }
    expect(router.push).toHaveBeenCalledWith({ name: 'assistant' })
    expect(useDeskStore().windows[0].id).toBe(result.window_id)
  })

  it('window.open does not navigate when already on assistant', async () => {
    const router = fakeRouter('assistant')
    installDeskCommands(router)
    await commandRegistry.execute('window.open', { module: 'chart' })
    expect(router.push).not.toHaveBeenCalled()
  })

  it('window.open rejects unknown modules with a clean error', async () => {
    installDeskCommands(fakeRouter('assistant'))
    await expect(commandRegistry.execute('window.open', { module: 'nope' })).rejects.toThrow(
      /modulo|module/i
    )
  })

  it('window.close / window.focus reject unknown ids', async () => {
    installDeskCommands(fakeRouter('assistant'))
    await expect(commandRegistry.execute('window.close', { window_id: 'ghost' })).rejects.toThrow()
    await expect(commandRegistry.execute('window.focus', { window_id: 'ghost' })).rejects.toThrow()
  })

  it('window.list returns the snapshot', async () => {
    installDeskCommands(fakeRouter('assistant'))
    await commandRegistry.execute('window.open', { module: 'chart' })
    const out = (await commandRegistry.execute('window.list', {})) as { windows: unknown[] }
    expect(out.windows).toHaveLength(1)
  })
})
