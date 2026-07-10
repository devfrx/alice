/**
 * Unit tests for utils/agentPrompts.ts
 *
 * Pure-function tests (vitest node env, no component mount). They cover the
 * tier_guidance round-trip helpers: normalisation of whatever the backend
 * stored into a complete four-key record, and pruning of blank overrides
 * before persisting (so the backend falls back to its built-in defaults).
 */
import { describe, it, expect } from 'vitest'

import {
  AGENT_TIERS,
  emptyTierGuidance,
  normaliseTierGuidance,
  pruneTierGuidance
} from './agentPrompts'

describe('AGENT_TIERS', () => {
  it('lists the four backend permission tiers in order', () => {
    expect(AGENT_TIERS.map((t) => t.key)).toEqual(['strict', 'auto_edits', 'plan', 'autopilot'])
  })
})

describe('emptyTierGuidance', () => {
  it('returns every tier key blank', () => {
    expect(emptyTierGuidance()).toEqual({
      strict: '',
      auto_edits: '',
      plan: '',
      autopilot: ''
    })
  })

  it('returns a fresh object each call (no shared mutation)', () => {
    const a = emptyTierGuidance()
    a.plan = 'mutated'
    expect(emptyTierGuidance().plan).toBe('')
  })
})

describe('normaliseTierGuidance', () => {
  it('fills missing tiers with blanks', () => {
    expect(normaliseTierGuidance({ plan: 'P' })).toEqual({
      strict: '',
      auto_edits: '',
      plan: 'P',
      autopilot: ''
    })
  })

  it('returns all-blank for null / undefined / non-object', () => {
    const blank = emptyTierGuidance()
    expect(normaliseTierGuidance(null)).toEqual(blank)
    expect(normaliseTierGuidance(undefined)).toEqual(blank)
  })

  it('drops unknown keys and non-string values', () => {
    const out = normaliseTierGuidance({
      strict: 'S',
      bogus: 'ignored',
      autopilot: 123 as unknown as string
    })
    expect(out).toEqual({
      strict: 'S',
      auto_edits: '',
      plan: '',
      autopilot: ''
    })
  })
})

describe('pruneTierGuidance', () => {
  it('drops blank and whitespace-only overrides', () => {
    expect(
      pruneTierGuidance({
        strict: 'keep',
        auto_edits: '',
        plan: '   ',
        autopilot: 'also keep'
      })
    ).toEqual({ strict: 'keep', autopilot: 'also keep' })
  })

  it('returns an empty object when nothing is customised', () => {
    expect(pruneTierGuidance(emptyTierGuidance())).toEqual({})
  })

  it('preserves text with surrounding meaningful content', () => {
    expect(pruneTierGuidance({ plan: ' guidance ' })).toEqual({
      plan: ' guidance '
    })
  })
})
