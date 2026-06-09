/**
 * scopeIndicatorLabel — pure label helpers for the scope indicator chip.
 *
 * Kept Vue-free so it can be unit-tested in the repo's `node` vitest
 * environment (no component mount). The chip component
 * ({@link ./ScopeIndicator.vue}) consumes these to render its compact label
 * and full-path tooltip.
 */

/** Compact chip label derived from a conversation's scope folders. */
export interface ScopeChipLabel {
  /** Text rendered on the chip. */
  text: string
  /** Whether the scope is empty (no folders) — drives the amber styling. */
  empty: boolean
}

/** Empty-scope chip text (also used as the empty sentinel). */
const EMPTY_TEXT = 'Nessuno scope'

/**
 * Last non-empty path segment, splitting on either separator and tolerating
 * trailing slashes (Windows `\` and POSIX `/`). Falls back to the raw path
 * when no segment can be extracted (e.g. a bare `/` or `\`).
 */
function basename(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] ?? path
}

/**
 * Build the compact chip label for a set of scope folders.
 *
 * - `[]` → `{ text: 'Nessuno scope', empty: true }`.
 * - one folder → `{ text: <basename>, empty: false }`.
 * - many folders → `{ text: '<firstBasename> +<N-1>', empty: false }`.
 */
export function scopeChipLabel(folders: string[]): ScopeChipLabel {
  if (folders.length === 0) return { text: EMPTY_TEXT, empty: true }
  const first = basename(folders[0])
  if (folders.length === 1) return { text: first, empty: false }
  return { text: `${first} +${folders.length - 1}`, empty: false }
}

/**
 * Full tooltip for the chip: every folder's full path on its own line, or a
 * friendly sentinel when the scope is empty.
 */
export function scopeTooltip(folders: string[]): string {
  if (folders.length === 0) return 'Nessuna cartella nello scope'
  return folders.join('\n')
}
