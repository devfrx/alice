/**
 * useModuleItemSelection — shared selection logic for multi-item workspace tiles.
 *
 * Charts, whiteboards and 3D models can all appear multiple times in a single
 * conversation. A workspace tile shows ONE of them at a time; this composable
 * resolves *which* one, with a consistent priority shared by every module:
 *
 *   1. The user's manual pick (set via `select()` — e.g. the ModuleSelectorBar).
 *   2. The `preferredId` supplied through the tile params (set by
 *      {@link useArtifactAutoOpen} when the tile is auto-opened for a new item).
 *   3. The most-recent item in the list (the natural default / fallback).
 *
 * A selection that becomes stale (its item was deleted, or belongs to a
 * conversation that is no longer loaded) transparently falls back to the
 * most-recent item, mirroring the resilient fallback the CAD/whiteboard modules
 * already had. Returns plain computed refs so callers stay declarative.
 *
 * @typeParam T - The item shape (ChartPayload, WhiteboardBoardItem, Artifact, …).
 */
import { computed, ref, watch, type ComputedRef } from 'vue'

export interface ModuleItemSelection<T> {
  /** The resolved item to display, or null when the list is empty. */
  current: ComputedRef<T | null>
  /** Id of {@link current}, or null. Bind to the selector's `modelValue`. */
  currentId: ComputedRef<string | null>
  /** Manually select an item by id (no-op visually if the id is unknown). */
  select: (id: string) => void
}

export function useModuleItemSelection<T>(config: {
  /** Reactive getter for the full item list (oldest → newest). */
  items: () => T[]
  /** Extract the stable id from an item. */
  getId: (item: T) => string
  /** Optional getter for the id supplied via tile params. */
  preferredId?: () => string | null | undefined
}): ModuleItemSelection<T> {
  const { items, getId, preferredId } = config

  /** The user's explicit pick; null until they choose or a param arrives. */
  const manualId = ref<string | null>(null)

  // Adopt the param-supplied id whenever it changes (and on mount). This keeps
  // auto-opened tiles focused on the freshly-generated item.
  watch(
    () => preferredId?.() ?? null,
    (id) => {
      if (id) manualId.value = id
    },
    { immediate: true }
  )

  const current = computed<T | null>(() => {
    const list = items()
    if (list.length === 0) return null
    const byId = (id: string | null | undefined): T | undefined =>
      id ? list.find((it) => getId(it) === id) : undefined
    // manual pick → param id → most-recent (last) item.
    return byId(manualId.value) ?? byId(preferredId?.()) ?? list[list.length - 1]
  })

  const currentId = computed<string | null>(() => (current.value ? getId(current.value) : null))

  function select(id: string): void {
    manualId.value = id
  }

  return { current, currentId, select }
}
