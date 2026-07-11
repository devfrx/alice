/**
 * toolTierView.ts — Pure tier→toolset reflection helpers.
 *
 * The permission TIER now governs the offered toolset via a sovereign
 * whitelist, so the in-chat "Strumenti" popover is a READ-ONLY reflection of
 * the active tier. This module holds the (Vue-free, unit-testable) logic that
 * maps a tier + the tool catalog into per-tool allowed/blocked flags.
 *
 * Mirrors the backend rule (Fase 7):
 * - Only the ``plan`` tier restricts: it blocks any tool whose capabilities
 *   include {@link READ_ONLY_BLOCKED_CAPS} (``fs_write`` / ``process_exec``),
 *   EXCEPT the always-allowed planning tools in {@link PLANNING_ALWAYS_ALLOW}.
 * - Every other tier (``strict`` / ``auto_edits`` / ``autopilot``) allows
 *   every tool.
 */

import type { ToolCatalogPlugin } from '../../types/settings'

/** Capability tags the ``plan`` tier withholds (write + execution). */
export const READ_ONLY_BLOCKED_CAPS = ['fs_write', 'process_exec'] as const

/**
 * Namespaced planning tools that stay available in every tier, even when their
 * capabilities would otherwise be blocked under ``plan``.
 */
export const PLANNING_ALWAYS_ALLOW = [
  'agent_update_tasks',
  'agent_write_plan',
  'agent_spawn_subagent',
  'agent_ask_user'
] as const

/** Whether a tool is one of the always-allowed planning tools. */
export function isPlanningTool(name: string): boolean {
  return (PLANNING_ALWAYS_ALLOW as readonly string[]).includes(name)
}

/**
 * Whether a tool is offered to the LLM under the given tier.
 *
 * @param tier - The active permission tier.
 * @param tool - The tool's namespaced name and capability tags.
 * @returns ``true`` when the tier offers the tool; ``false`` only when the
 *   ``plan`` tier withholds a write/exec tool that is not a planning tool.
 */
export function isToolAllowedInTier(
  tier: string,
  tool: { name: string; capabilities: string[] }
): boolean {
  if (tier !== 'plan') return true
  const blocked = tool.capabilities.some((cap) =>
    (READ_ONLY_BLOCKED_CAPS as readonly string[]).includes(cap)
  )
  if (!blocked) return true
  // Planning tools are sovereign — allowed even with a blocked capability.
  return isPlanningTool(tool.name)
}

/** A plugin group with each tool's tier-derived allowed/planning flags. */
export interface TierToolGroup {
  plugin: string
  tools: Array<{ name: string; label: string; allowed: boolean; planning: boolean }>
}

/**
 * Project the tool catalog through a tier into per-tool allowed flags.
 *
 * In the ``plan`` tier, tools are reordered within each group so planning and
 * other allowed tools lead and blocked (write/exec) tools sink to the bottom;
 * other tiers preserve the catalog order. ``Array.prototype.sort`` is stable,
 * so the original order is preserved within each rank.
 *
 * @param tier - The active permission tier.
 * @param catalog - The tool catalog grouped by plugin.
 * @returns The same grouping with `allowed` / `planning` flags per tool.
 */
export function tierToolView(tier: string, catalog: ToolCatalogPlugin[]): TierToolGroup[] {
  return catalog.map((group) => {
    const tools = group.tools.map((tool) => ({
      name: tool.name,
      label: tool.label,
      allowed: isToolAllowedInTier(tier, tool),
      planning: isPlanningTool(tool.name)
    }))
    if (tier === 'plan') {
      tools.sort((a, b) => {
        // Planning tools lead.
        if (a.planning !== b.planning) return a.planning ? -1 : 1
        // Then allowed tools before blocked ones.
        if (a.allowed !== b.allowed) return a.allowed ? -1 : 1
        return 0
      })
    }
    return { plugin: group.plugin, tools }
  })
}

/** Short Italian one-liner describing what the tier offers. */
export function tierSummary(tier: string): string {
  switch (tier) {
    case 'plan':
      return 'Sola lettura: scrittura ed esecuzione disattivate; pianificazione in evidenza.'
    case 'auto_edits':
      return 'Tutti gli strumenti; scritture nello scope senza conferma.'
    case 'autopilot':
      return 'Tutti gli strumenti; nessuna conferma.'
    case 'strict':
    default:
      return 'Tutti gli strumenti disponibili; conferma per le azioni sensibili.'
  }
}
