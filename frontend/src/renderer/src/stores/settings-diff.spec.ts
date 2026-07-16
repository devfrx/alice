import { describe, expect, it } from 'vitest'
import { diffConfigPayload } from './settings'
import type { ConfigUpdatePayload } from './settings'

const base: ConfigUpdatePayload = {
  llm: { temperature: 0.7, max_tokens: -1, provider: 'lmstudio' },
  ui: { theme: 'dark', language: 'it' },
  email: { enabled: false, imap_port: 993 }
}

describe('diffConfigPayload', () => {
  it('returns only the changed keys, dropping untouched sections', () => {
    const next: ConfigUpdatePayload = {
      llm: { temperature: 0.9, max_tokens: -1, provider: 'lmstudio' },
      ui: { theme: 'dark', language: 'it' },
      email: { enabled: false, imap_port: 993 }
    }
    expect(diffConfigPayload(base, next)).toEqual({ llm: { temperature: 0.9 } })
  })

  it('returns an empty object when nothing changed', () => {
    expect(diffConfigPayload(base, structuredClone(base))).toEqual({})
  })

  it('compares arrays by value', () => {
    const prev: ConfigUpdatePayload = {
      llm: { openrouter_favorites: ['a/b'] }
    }
    const next: ConfigUpdatePayload = {
      llm: { openrouter_favorites: ['a/b', 'c/d'] }
    }
    expect(diffConfigPayload(prev, next)).toEqual({
      llm: { openrouter_favorites: ['a/b', 'c/d'] }
    })
  })

  it('never resurrects keys absent from the next payload', () => {
    const prev: ConfigUpdatePayload = { email: { enabled: true, imap_port: 1 } }
    const next: ConfigUpdatePayload = { email: { enabled: true } }
    expect(diffConfigPayload(prev, next)).toEqual({})
  })
})
