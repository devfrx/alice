/**
 * agentPrompts — pure helpers for the "Agente / Persona" settings section.
 *
 * Kept Vue-free so they can be unit-tested in the repo's `node` vitest
 * environment (no component mount). Both the settings store
 * ({@link ../stores/settings.ts}) and the section component
 * ({@link ../components/settings/AgentPersonaSettings.vue}) consume these.
 *
 * They mirror the backend contract `agent.prompts.tier_guidance`, a
 * `dict[str, str]` keyed by permission-tier strings where a blank value means
 * "use the built-in default text for that tier".
 */

import type { AgentTier } from '../types/settings'

/** Display metadata for one permission tier's guidance editor. */
export interface AgentTierMeta {
  /** Config key under `agent.prompts.tier_guidance`. */
  key: AgentTier
  /** Italian label shown above the textarea. */
  label: string
  /** Short description of what the tier allows. */
  hint: string
}

/**
 * The four permission tiers, in display order. Keys match the backend
 * `PermissionMode` values; labels mirror the in-chat permission-mode UI.
 */
export const AGENT_TIERS: readonly AgentTierMeta[] = [
  {
    key: 'strict',
    label: 'Conferma',
    hint: 'Ogni strumento che modifica o esegue richiede una conferma esplicita.'
  },
  {
    key: 'auto_edits',
    label: 'Auto-modifiche',
    hint: 'Le modifiche ai file avvengono senza conferma; i comandi restano confermati.'
  },
  {
    key: 'plan',
    label: 'Pianifica',
    hint: 'Sola lettura: l’agente analizza e pianifica senza eseguire modifiche.'
  },
  {
    key: 'autopilot',
    label: 'Autopilota',
    hint: 'L’agente esegue tutto autonomamente, senza richiedere conferme.'
  }
] as const

/** Build a fresh tier_guidance map with every tier present and blank. */
export function emptyTierGuidance(): Record<AgentTier, string> {
  return { strict: '', auto_edits: '', plan: '', autopilot: '' }
}

/**
 * Normalise a loaded tier_guidance map into a complete, string-valued record.
 *
 * Guarantees every tier key is present (defaulting to `''`), coerces values to
 * strings, and drops any unknown keys — so the UI can bind the four textareas
 * unconditionally regardless of what the backend stored.
 *
 * @param raw - The `agent.prompts.tier_guidance` value from the backend (any shape).
 * @returns A record with exactly the four tier keys.
 */
export function normaliseTierGuidance(
  raw: Record<string, unknown> | null | undefined
): Record<AgentTier, string> {
  const out = emptyTierGuidance()
  if (!raw || typeof raw !== 'object') return out
  for (const meta of AGENT_TIERS) {
    const value = raw[meta.key]
    if (typeof value === 'string') out[meta.key] = value
  }
  return out
}

/**
 * Prune a tier_guidance map for persistence.
 *
 * Drops blank / whitespace-only overrides so the backend transparently falls
 * back to its built-in per-tier default text. The result only contains the
 * tiers the user actually customised.
 *
 * @param map - The current editor state (tier key → text).
 * @returns A map with only the non-blank overrides.
 */
export function pruneTierGuidance(map: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(map)) {
    if (value && value.trim()) out[key] = value
  }
  return out
}
