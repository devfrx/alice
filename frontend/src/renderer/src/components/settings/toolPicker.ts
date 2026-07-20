/**
 * Pure logic for the tool picker in {@link ./PermissionRulesManager.vue}.
 *
 * Extracted so it is testable in the vitest node env (no component mount):
 * the catalog filtering (`filterCatalog`) and the keyboard-highlight
 * navigation (`moveHighlight`). The component keeps only the glue (refs,
 * focus/blur timing, DOM events).
 */
import type { ToolCatalogEntry } from '../../types/permission'

/** Alphabetical comparator by tool name (stable tie-break everywhere). */
function byName(a: ToolCatalogEntry, b: ToolCatalogEntry): number {
  return a.name.localeCompare(b.name)
}

/**
 * Filter the tool catalog for the picker dropdown.
 *
 * Matching is case-insensitive on `name`, `label` and `plugin`. Entries whose
 * `name` starts with the query rank before plain substring matches; within
 * each rank the order is alphabetical by name. An empty (or whitespace-only)
 * query returns the first `limit` entries alphabetically.
 *
 * Args:
 *     entries: The full catalog.
 *     query: Raw user input (trimmed internally).
 *     limit: Maximum number of results (default 12).
 *
 * Returns:
 *     At most `limit` matching entries, ranked as described; `[]` when
 *     nothing matches.
 */
export function filterCatalog(
  entries: ToolCatalogEntry[],
  query: string,
  limit = 12
): ToolCatalogEntry[] {
  const q = query.trim().toLowerCase()
  if (!q) return [...entries].sort(byName).slice(0, limit)

  const prefix: ToolCatalogEntry[] = []
  const substring: ToolCatalogEntry[] = []
  for (const e of entries) {
    const name = e.name.toLowerCase()
    if (name.startsWith(q)) {
      prefix.push(e)
    } else if (
      name.includes(q) ||
      e.label.toLowerCase().includes(q) ||
      e.plugin.toLowerCase().includes(q)
    ) {
      substring.push(e)
    }
  }
  prefix.sort(byName)
  substring.sort(byName)
  return [...prefix, ...substring].slice(0, limit)
}

/**
 * Move the keyboard highlight by `delta` with wrap-around.
 *
 * From the no-highlight state (`current === -1`) a downward move enters at
 * the first item and an upward move at the last. An empty list always yields
 * `-1`.
 *
 * Args:
 *     current: Current highlight index (`-1` when none).
 *     delta: Step, typically `+1` (ArrowDown) or `-1` (ArrowUp).
 *     count: Number of items in the list.
 *
 * Returns:
 *     The new highlight index in `[0, count)`, or `-1` when `count <= 0`.
 */
export function moveHighlight(current: number, delta: number, count: number): number {
  if (count <= 0) return -1
  if (current < 0) return delta >= 0 ? 0 : count - 1
  return (((current + delta) % count) + count) % count
}
