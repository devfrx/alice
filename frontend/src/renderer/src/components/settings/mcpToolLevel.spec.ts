/**
 * Unit tests for components/settings/mcpToolLevel.ts
 *
 * Pure-function tests (vitest node env, no component mount) covering the
 * badge derivation for MCP tools (level -> label/variant, all three branches)
 * and for the per-server trust flag (trust_annotations -> label/variant).
 */
import { describe, it, expect } from 'vitest'

import type { McpServerInfo, McpServerTool } from '../../types/mcp'
import { serverTrustBadge, toolLevelBadge } from './mcpToolLevel'

/** Minimal tool factory — only `level` matters for the badge. */
function tool(level: McpServerTool['level']): McpServerTool {
  return {
    name: 'test_tool',
    description: 'a test tool',
    level,
    risk_level: level === 'read_only' ? 'safe' : 'dangerous',
    requires_confirmation: level !== 'read_only'
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
      variant: 'success'
    })
  })

  it('maps write to a warning badge', () => {
    expect(toolLevelBadge(tool('write'))).toEqual({
      label: 'scrittura',
      variant: 'warning'
    })
  })

  it('maps fallback to a danger badge with the explicit long label', () => {
    expect(toolLevelBadge(tool('fallback'))).toEqual({
      label: 'non annotato → trattato come distruttivo',
      variant: 'danger'
    })
  })
})

describe('serverTrustBadge', () => {
  it('maps trust_annotations=true to a success badge', () => {
    expect(serverTrustBadge(server(true))).toEqual({
      label: 'annotations fidate',
      variant: 'success'
    })
  })

  it('maps trust_annotations=false to a warning badge', () => {
    expect(serverTrustBadge(server(false))).toEqual({
      label: 'annotations non fidate',
      variant: 'warning'
    })
  })
})
