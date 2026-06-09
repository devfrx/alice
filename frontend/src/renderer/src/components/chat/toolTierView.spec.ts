/**
 * Unit tests for components/chat/toolTierView.ts
 *
 * Pure-function tests (vitest node env, no component mount). They cover the
 * tier→tool reflection rule (only ``plan`` restricts write/exec, planning tools
 * stay sovereign), the grouped projection + plan-tier reordering, and the
 * per-tier Italian summary.
 */
import { describe, it, expect } from 'vitest'

import type { ToolCatalogPlugin } from '../../types/settings'
import {
  isToolAllowedInTier,
  tierToolView,
  tierSummary,
  READ_ONLY_BLOCKED_CAPS,
  PLANNING_ALWAYS_ALLOW,
} from './toolTierView'

describe('isToolAllowedInTier', () => {
  it('blocks a write tool under the plan tier', () => {
    expect(
      isToolAllowedInTier('plan', { name: 'pc_automation_write_file', capabilities: ['fs_write'] }),
    ).toBe(false)
  })

  it('blocks an exec tool under the plan tier', () => {
    expect(
      isToolAllowedInTier('plan', { name: 'terminal_run', capabilities: ['process_exec'] }),
    ).toBe(false)
  })

  it('always allows a planning tool under the plan tier', () => {
    expect(
      isToolAllowedInTier('plan', { name: 'agent_write_plan', capabilities: ['planning'] }),
    ).toBe(true)
  })

  it('keeps a planning tool allowed even when it carries a blocked capability', () => {
    expect(
      isToolAllowedInTier('plan', { name: 'agent_write_plan', capabilities: ['fs_write'] }),
    ).toBe(true)
  })

  it('allows a read-only tool under the plan tier', () => {
    expect(
      isToolAllowedInTier('plan', { name: 'web_search', capabilities: ['network'] }),
    ).toBe(true)
  })

  it('allows write/exec tools under every non-plan tier', () => {
    expect(
      isToolAllowedInTier('autopilot', { name: 'terminal_run', capabilities: ['process_exec'] }),
    ).toBe(true)
    expect(
      isToolAllowedInTier('strict', { name: 'pc_automation_write_file', capabilities: ['fs_write'] }),
    ).toBe(true)
    expect(
      isToolAllowedInTier('auto_edits', { name: 'terminal_run', capabilities: ['process_exec'] }),
    ).toBe(true)
  })

  it('exposes the canonical blocked-cap and planning constants', () => {
    expect(READ_ONLY_BLOCKED_CAPS).toEqual(['fs_write', 'process_exec'])
    expect(PLANNING_ALWAYS_ALLOW).toEqual([
      'agent_update_tasks',
      'agent_write_plan',
      'agent_spawn_subagent',
      'agent_ask_user',
    ])
  })
})

const catalog: ToolCatalogPlugin[] = [
  {
    plugin: 'agent',
    tools: [
      { name: 'pc_automation_write_file', label: 'write_file', description: '', enabled: true, capabilities: ['fs_write'] },
      { name: 'agent_write_plan', label: 'write_plan', description: '', enabled: true, capabilities: ['planning'] },
      { name: 'web_search', label: 'search', description: '', enabled: true, capabilities: ['network'] },
    ],
  },
  {
    plugin: 'terminal',
    tools: [
      { name: 'terminal_run', label: 'run', description: '', enabled: true, capabilities: ['process_exec'] },
    ],
  },
]

describe('tierToolView', () => {
  it('marks write/exec tools as blocked under the plan tier', () => {
    const view = tierToolView('plan', catalog)
    const agent = view.find((g) => g.plugin === 'agent')!
    const write = agent.tools.find((t) => t.name === 'pc_automation_write_file')!
    const term = view.find((g) => g.plugin === 'terminal')!.tools[0]
    expect(write.allowed).toBe(false)
    expect(term.allowed).toBe(false)
  })

  it('floats planning (then allowed) tools first within a group under plan', () => {
    const view = tierToolView('plan', catalog)
    const agent = view.find((g) => g.plugin === 'agent')!
    // planning leads, allowed read tool next, blocked write tool last.
    expect(agent.tools.map((t) => t.name)).toEqual([
      'agent_write_plan',
      'web_search',
      'pc_automation_write_file',
    ])
    expect(agent.tools[0].planning).toBe(true)
  })

  it('allows everything and preserves order under non-plan tiers', () => {
    const view = tierToolView('autopilot', catalog)
    const agent = view.find((g) => g.plugin === 'agent')!
    expect(agent.tools.every((t) => t.allowed)).toBe(true)
    expect(agent.tools.map((t) => t.name)).toEqual([
      'pc_automation_write_file',
      'agent_write_plan',
      'web_search',
    ])
  })
})

describe('tierSummary', () => {
  it('returns a non-empty Italian summary for every tier', () => {
    for (const tier of ['strict', 'auto_edits', 'plan', 'autopilot']) {
      expect(tierSummary(tier).length).toBeGreaterThan(0)
    }
  })

  it('uses distinct copy per tier and a sensible fallback', () => {
    expect(tierSummary('plan')).toContain('Sola lettura')
    expect(tierSummary('strict')).not.toBe(tierSummary('plan'))
    expect(tierSummary('unknown').length).toBeGreaterThan(0)
  })
})
