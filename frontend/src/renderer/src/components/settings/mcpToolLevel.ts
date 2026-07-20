/**
 * Badge derivation for the MCP settings panel.
 *
 * Pure functions (no Vue imports) so they are unit-testable in the vitest
 * node environment. The `level` of an MCP tool is derived by the backend gate
 * from the provenance of the server annotations (spec Fase 2 §6.4):
 * - `read_only`  — annotated `readOnlyHint=true` on a trusted server;
 * - `write`      — annotated as writing on a trusted server;
 * - `fallback`   — not annotated OR untrusted server → the gate treats it as
 *                  destructive (conservative default).
 */

import type { McpServerInfo, McpServerTool } from '../../types/mcp'

export interface McpBadge {
  label: string
  variant: 'success' | 'warning' | 'danger'
}

/** Badge (label + color variant) for a tool's derived permission level. */
export function toolLevelBadge(tool: McpServerTool): McpBadge {
  switch (tool.level) {
    case 'read_only':
      return { label: 'sola lettura', variant: 'success' }
    case 'write':
      return { label: 'scrittura', variant: 'warning' }
    case 'fallback':
      return { label: 'non annotato → trattato come distruttivo', variant: 'danger' }
  }
}

/** Badge for the per-server `trust_annotations` flag (read-only, from config). */
export function serverTrustBadge(server: McpServerInfo): {
  label: string
  variant: 'success' | 'warning'
} {
  return server.trust_annotations
    ? { label: 'annotations fidate', variant: 'success' }
    : { label: 'annotations non fidate', variant: 'warning' }
}
