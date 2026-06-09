import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { useServicesStore } from './services'

describe('services polling back-off', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('extends the poll interval while down and resets when up', () => {
    const store = useServicesStore()
    expect(store.nextPollDelay(4000)).toBe(4000) // healthy baseline
    store.noteStatus('lmstudio', 'down')
    const d1 = store.nextPollDelay(4000)
    const d2 = store.nextPollDelay(4000)
    expect(d1).toBeGreaterThan(4000)
    expect(d2).toBeGreaterThanOrEqual(d1)
    expect(d2).toBeLessThanOrEqual(30000)
    store.noteStatus('lmstudio', 'up')
    expect(store.nextPollDelay(4000)).toBe(4000)
  })
})
