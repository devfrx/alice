<script setup lang="ts">
/**
 * TldrawCanvas.vue — Vue wrapper that mounts a React tldraw editor.
 *
 * Uses React's `createRoot` to render the `TldrawApp` component
 * inside a Vue host element (React-island pattern).
 * If no snapshot is provided as prop, it fetches it from the backend.
 */
import { ref, onMounted, onBeforeUnmount, watch, type PropType } from 'vue'
import { api } from '@renderer/services/api'

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

const containerRef = ref<HTMLDivElement | null>(null)

/* React root handle */
let root: { render: (el: unknown) => void; unmount: () => void } | null = null

async function mountReact(): Promise<void> {
  if (!containerRef.value) return

  /* If no snapshot provided as prop, fetch it from the backend */
  let resolvedSnapshot = props.snapshot as Record<string, unknown> | null
  if (!resolvedSnapshot && props.boardId) {
    try {
      const spec = await api.getWhiteboard(props.boardId)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      resolvedSnapshot = (spec as any).snapshot ?? null
    } catch {
      /* Board may not exist yet or network error — start empty */
    }
  }

  /* Dynamic imports keep React out of the main Vue bundle */
  const [reactModule, reactDomModule, tldrawAppModule] = await Promise.all([
    import('react'),
    import('react-dom/client'),
    import('./tldraw-app')
  ])

  const createElement = reactModule.createElement
  const createRoot = reactDomModule.createRoot
  const TldrawApp = tldrawAppModule.default

  /* Unmount any previous React root (board switch) */
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
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      onDocumentChange: (snap: any) => emit('change', snap as Record<string, unknown>)
    })
  )
  root = newRoot as { render: (el: unknown) => void; unmount: () => void }
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

onBeforeUnmount(() => {
  if (root) {
    root.unmount()
    root = null
  }
})
</script>

<template>
  <div ref="containerRef" class="tldraw-canvas" />
</template>

<style scoped>
.tldraw-canvas {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
  border-radius: var(--radius-lg, 12px);
}

/* Ensure tldraw fills the container */
.tldraw-canvas :deep(.alice-tldraw-wrapper) {
  width: 100%;
  height: 100%;
}

/* ── AL\CE theme overrides for tldraw ─────────────────────── */
.tldraw-canvas :deep(.tl-container) {
  --color-background: var(--surface-0, #161616);
  --color-text-0: var(--text-primary, #EDEDE9);
  --color-text-1: var(--text-secondary, #A09B90);
  --color-text-3: var(--text-muted, #5F5B53);
  --color-panel: var(--surface-2, #232323);
  --color-low: var(--surface-1, #1C1C1C);
  --color-muted-0: var(--surface-3, #2A2A2A);
  --color-muted-1: var(--surface-4, #323232);
  --color-muted-2: #3a3a3a;
  --color-hint: var(--text-muted, #5F5B53);
  --color-overlay: rgba(0, 0, 0, 0.5);
  --color-divider: var(--border, rgba(237, 227, 213, 0.08));
  --color-focus: var(--accent, #E8DCC8);
  --color-selected: var(--accent, #E8DCC8);
  --color-selection-stroke: var(--accent, #E8DCC8);
  --color-selection-fill: rgba(232, 220, 200, 0.08);
  --color-primary: var(--accent, #E8DCC8);
  --color-warn: #e8a87c;
  --color-text-shadow: none;
  --radius: 8px;
}
</style>
