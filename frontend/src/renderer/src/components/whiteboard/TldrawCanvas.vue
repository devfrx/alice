<script setup lang="ts">
/**
 * TldrawCanvas.vue — Vue wrapper that mounts a React tldraw editor.
 *
 * Uses React's `createRoot` to render the `TldrawApp` component
 * inside a Vue host element (React-island pattern).
 * If no snapshot is provided as prop, it fetches it from the backend.
 */
import { ref, onMounted, onBeforeUnmount, watch, type PropType } from 'vue'
import { useArtifactsStore } from '../../stores/artifacts'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps({
  /** Board ID used to trigger full remount on board switch. */
  boardId: { type: String, required: true },
  /** Initial tldraw snapshot to load (opaque JSON object from backend). */
  snapshot: { type: Object as PropType<Record<string, unknown> | null>, default: null }
})

const emit = defineEmits<{
  /** Emitted when the user edits the canvas (debounced by tldraw-app). */
  (e: 'change', snapshot: Record<string, unknown>): void
}>()

const artifactsStore = useArtifactsStore()

const containerRef = ref<HTMLDivElement | null>(null)

/** True when the board JSON file no longer exists on disk (404). */
const isOrphaned = ref(false)

/**
 * True once the in-flight `mountReact()` call has fully resolved. Gates the
 * live-update watcher below so a store update that lands mid-mount (a race
 * between this component's own fetch and the parent's) cannot trigger a
 * second, redundant reload right after the initial/board-switch one.
 */
const canvasReady = ref(false)

/* React root handle */
let root: { render: (el: unknown) => void; unmount: () => void } | null = null

/**
 * JSON of the snapshot currently rendered by the mounted editor. Used by the
 * live-update watcher to tell a genuine external change apart from the echo
 * of our own save (`change` emit → `saveContent` PATCH → backend emits
 * `artifact.updated` → this client's own WS handler refetches content into
 * the store — which would otherwise re-trigger a reload of what we just
 * drew).
 */
let mountedSnapshotJson: string | null = null

async function mountReact(): Promise<void> {
  if (!containerRef.value) return

  isOrphaned.value = false
  canvasReady.value = false

  /* Prefer the freshest cached content (kept current by `artifact.updated`
   * live-updates), then the prop, then fetch THROUGH THE STORE so the cache
   * gets populated — the live-update path relies on a cache entry existing
   * (`applyArtifactUpdated` only force-refetches cached content). */
  let resolvedSnapshot =
    (artifactsStore.contents[props.boardId]?.snapshot as Record<string, unknown> | undefined) ??
    (props.snapshot as Record<string, unknown> | null)
  if (!resolvedSnapshot && props.boardId) {
    const content = await artifactsStore.fetchContent(props.boardId)
    if (content === null) {
      /* Fetch failed (404 board deleted, or network error) — orphan state */
      isOrphaned.value = true
      return
    }
    const snap = content.snapshot
    resolvedSnapshot = snap && typeof snap === 'object' ? (snap as Record<string, unknown>) : null
  }
  mountedSnapshotJson = resolvedSnapshot ? JSON.stringify(resolvedSnapshot) : null

  /* Dynamic imports keep React out of the main Vue bundle */
  const [reactModule, reactDomModule, tldrawAppModule] = await Promise.all([
    import('react'),
    import('react-dom/client'),
    import('./tldraw-app')
  ])

  const createElement = reactModule.createElement
  const createRoot = reactDomModule.createRoot
  const TldrawApp = tldrawAppModule.default

  /* Unmount any previous React root (board switch or live reload) */
  if (root) {
    root.unmount()
    root = null
  }

  const newRoot = createRoot(containerRef.value)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const snapshotProp = resolvedSnapshot as any
  newRoot.render(
    createElement(TldrawApp, {
      snapshot: snapshotProp,
      onDocumentChange: (snap: unknown) => {
        mountedSnapshotJson = JSON.stringify(snap)
        emit('change', snap as Record<string, unknown>)
      }
    })
  )
  root = newRoot as { render: (el: unknown) => void; unmount: () => void }
  canvasReady.value = true

  /* Catch-up: a store update landing while the dynamic imports were in
   * flight is consumed silently (the live-update watcher is gated by
   * `canvasReady`). If the cache now differs from what was just mounted,
   * run one more reload — it converges immediately because the reload
   * prefers the cache, making the two JSONs equal. */
  const latest = artifactsStore.contents[props.boardId]?.snapshot
  if (latest !== undefined && JSON.stringify(latest) !== mountedSnapshotJson) {
    void mountReact()
  }
}

onMounted(() => {
  mountReact()
})

/* Full remount when the board switches */
watch(
  () => props.boardId,
  () => {
    if (root) {
      root.unmount()
      root = null
    }
    mountReact()
  }
)

/**
 * Live-update: when this board's cached JSON content changes to something
 * other than what we just rendered/saved, reload the canvas in place (same
 * Vue component instance, same board — only the internal React root is
 * recreated, via the existing `mountReact()` load path). This is what makes
 * an `artifact.updated` event (another client, or an agent tool editing the
 * board) show up live without navigating away from the open board.
 */
watch(
  () => artifactsStore.contents[props.boardId]?.snapshot,
  (snap) => {
    if (!canvasReady.value || snap === undefined) return
    const json = JSON.stringify(snap ?? null)
    if (json === mountedSnapshotJson) return // our own save echo — ignore
    mountReact()
  }
)

onBeforeUnmount(() => {
  if (root) {
    root.unmount()
    root = null
  }
})
</script>

<template>
  <div class="tldraw-host">
    <!-- Orphan state: board was deleted from the whiteboard page -->
    <div v-if="isOrphaned" class="tldraw-orphaned">
      <AppIcon name="whiteboard-deleted" :size="24" :stroke-width="1.5" class="tldraw-orphaned__icon" />
      <p class="tldraw-orphaned__text">Lavagna non più disponibile</p>
      <p class="tldraw-orphaned__hint">Il file è stato eliminato dalla pagina Lavagne</p>
    </div>
    <!-- Canvas container (hidden when orphaned) -->
    <div v-else ref="containerRef" class="tldraw-canvas" />
  </div>
</template>

<style scoped>
.tldraw-host {
  width: 100%;
  height: 100%;
  position: relative;
}

.tldraw-canvas {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
  border-radius: var(--radius-lg);
}

.tldraw-orphaned {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  width: 100%;
  height: 100%;
  color: var(--text-muted);
  text-align: center;
  padding: var(--space-6);
}

.tldraw-orphaned__icon {
  opacity: 0.4;
  margin-bottom: var(--space-2);
}

.tldraw-orphaned__text {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: var(--weight-medium);
  margin: 0;
}

.tldraw-orphaned__hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin: 0;
}

/* Ensure tldraw fills the container */
.tldraw-canvas :deep(.alice-tldraw-wrapper) {
  width: 100%;
  height: 100%;
}

/* ── AL\CE theme overrides for tldraw ─────────────────────── */
/*
 * tldraw reads these CSS variables from its own --color-* namespace.
 * We map them to our design-system tokens here so tldraw picks up
 * the active theme (dark/light) automatically. Literal hex fallbacks
 * below are required because tldraw internals sometimes expect
 * resolved colors — they match the dark palette.
 */
.tldraw-canvas :deep(.tl-container) {
  --color-background: var(--surface-0);
  --color-text-0: var(--text-primary);
  --color-text-1: var(--text-secondary);
  --color-text-3: var(--text-muted);
  --color-panel: var(--surface-2);
  --color-low: var(--surface-1);
  --color-muted-0: var(--surface-3);
  --color-muted-1: var(--surface-4);
  --color-muted-2: #3a3a3a;
  --color-hint: var(--text-muted);
  --color-overlay: var(--black-heavy);
  --color-divider: var(--border);
  --color-focus: var(--accent);
  --color-selected: var(--accent);
  --color-selection-stroke: var(--accent);
  --color-selection-fill: var(--accent-dim);
  --color-primary: var(--accent);
  --color-warn: #e8a87c;
  --color-text-shadow: none;
  --radius: var(--radius-md);
}
</style>
