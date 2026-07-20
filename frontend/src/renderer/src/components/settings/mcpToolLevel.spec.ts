/**
 * Unit tests for components/settings/mcpToolLevel.ts
 *
 * Pure-function tests (vitest node env, no component mount) covering the
 * badge derivation for MCP tools (level -> label/shortLabel/variant, all
 * three branches), the localized risk labels, the tooltip builder, and the
 * per-server trust badge (trust_annotations -> label/variant).
 */
import { describe, it, expect } from 'vitest'

import type { McpServerInfo, McpServerTool } from '../../types/mcp'
import { riskLevelLabel, serverTrustBadge, toolLevelBadge, toolTitle } from './mcpToolLevel'

/** Minimal tool factory — only `level` matters for the badge. */
function tool(
  level: McpServerTool['level'],
  overrides: Partial<McpServerTool> = {}
): McpServerTool {
  return {
    name: 'test_tool',
    description: 'a test tool',
    level,
    risk_level: level === 'read_only' ? 'safe' : 'dangerous',
    requires_confirmation: level !== 'read_only',
    ...overrides
  }
}

/** Minimal server factory — only `trust_annotations` matters for the badge. */
function server(trustAnnotations: boolean): McpServerInfo {
  return {
    name: 'test_server',
    transport: 'stdio',
    enabled: true,
    command: ['echo'],
    url: null,
    status: 'connected',
    trust_annotations: trustAnnotations,
    tools: []
  }
}

describe('toolLevelBadge', () => {
  it('maps read_only to a success badge', () => {
    expect(toolLevelBadge(tool('read_only'))).toEqual({
      label: 'sola lettura',
      shortLabel: 'sola lettura',
      variant: 'success'
    })
  })

  it('maps write to a warning badge', () => {
    expect(toolLevelBadge(tool('write'))).toEqual({
      label: 'scrittura',
      shortLabel: 'scrittura',
      variant: 'warning'
    })
  })

  it('maps fallback to a danger badge with the explicit long label and a short tag label', () => {
    expect(toolLevelBadge(tool('fallback'))).toEqual({
      label: 'non annotato → trattato come distruttivo',
      shortLabel: 'non annotato',
      variant: 'danger'
    })
  })
})

describe('riskLevelLabel', () => {
  it.each([
    ['safe', 'sicuro'],
    ['medium', 'medio'],
    ['dangerous', 'pericoloso'],
    ['forbidden', 'vietato']
  ] as const)('localizes %s to %s', (risk, expected) => {
    expect(riskLevelLabel(risk)).toBe(expected)
  })
})

describe('toolTitle', () => {
  it('composes description, full level label and localized risk (with confirmation)', () => {
    const t = tool('fallback', { risk_level: 'dangerous', requires_confirmation: true })
    expect(toolTitle(t)).toBe(
      'a test tool\nLivello: non annotato → trattato come distruttivo — rischio pericoloso, con conferma'
    )
  })

  it('marks tools that run without confirmation', () => {
    const t = tool('read_only', { risk_level: 'safe', requires_confirmation: false })
    expect(toolTitle(t)).toBe('a test tool\nLivello: sola lettura — rischio sicuro, senza conferma')
  })
})

describe('serverTrustBadge', () => {
  it('maps trust_annotations=true to a success badge', () => {
    expect(serverTrustBadge(server(true))).toEqual({
      label: 'annotations fidate',
      shortLabel: 'annotations fidate',
      variant: 'success'
    })
  })

  it('maps trust_annotations=false to a warning badge', () => {
    expect(serverTrustBadge(server(false))).toEqual({
      label: 'annotations non fidate',
      shortLabel: 'annotations non fidate',
      variant: 'warning'
    })
  })
})
