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
 *
 * NOTE (invariant wording): the "trattato come distruttivo" phrasing also
 * appears — differentiated per cause — in the confirmation-card warning built
 * by `components/chat/toolConfirmationView.ts::buildFallbackWarning`. The two
 * modules serve different domains (settings panel vs live confirmation) and
 * are intentionally NOT consolidated, but their wording must stay in sync.
 */

import type { McpServerInfo, McpServerTool } from '../../types/mcp'

export interface McpBadge {
  label: string
  /** Short in-tag variant of `label` (tags cannot afford the long fallback label). */
  shortLabel: string
  variant: 'success' | 'warning' | 'danger'
}

/** Trust badge: same shape as `McpBadge` but never `danger`. */
export type McpTrustBadge = McpBadge & { variant: 'success' | 'warning' }

/** Badge (labels + color variant) for a tool's derived permission level. */
export function toolLevelBadge(tool: McpServerTool): McpBadge {
  switch (tool.level) {
    case 'read_only':
      return { label: 'sola lettura', shortLabel: 'sola lettura', variant: 'success' }
    case 'write':
      return { label: 'scrittura', shortLabel: 'scrittura', variant: 'warning' }
    case 'fallback':
      return {
        label: 'non annotato → trattato come distruttivo',
        shortLabel: 'non annotato',
        variant: 'danger'
      }
  }
}

/** Italian label for the gate risk level (exhaustive — no wire vocabulary in tooltips). */
export function riskLevelLabel(risk: McpServerTool['risk_level']): string {
  switch (risk) {
    case 'safe':
      return 'sicuro'
    case 'medium':
      return 'medio'
    case 'dangerous':
      return 'pericoloso'
    case 'forbidden':
      return 'vietato'
  }
}

/** Tooltip for a tool tag: description + full derived level + localized gate risk. */
export function toolTitle(tool: McpServerTool): string {
  const badge = toolLevelBadge(tool)
  const confirm = tool.requires_confirmation ? 'con conferma' : 'senza conferma'
  return `${tool.description}\nLivello: ${badge.label} — rischio ${riskLevelLabel(tool.risk_level)}, ${confirm}`
}

/** Badge for the per-server `trust_annotations` flag (read-only, from config). */
export function serverTrustBadge(server: McpServerInfo): McpTrustBadge {
  return server.trust_annotations
    ? { label: 'annotations fidate', shortLabel: 'annotations fidate', variant: 'success' }
    : { label: 'annotations non fidate', shortLabel: 'annotations non fidate', variant: 'warning' }
}
