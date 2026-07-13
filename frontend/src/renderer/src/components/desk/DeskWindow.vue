<!-- components/desk/DeskWindow.vue -->
<script setup lang="ts">
/**
 * DeskWindow — the atelier "sheet": floating window chrome around a catalog
 * module (same MODULE_REGISTRY as the Workspace tiles, different dress).
 * Geometry/z/focus live in the desk store; this component renders one window
 * and wires drag (header) + resize (grips).
 *
 * Minimized windows are hidden with v-show (NOT unmounted) so live module
 * views (xterm, canvases) survive the round-trip to the dock.
 */
import { computed, defineAsyncComponent, h } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import AliceSpinner from '../ui/AliceSpinner.vue'
import { useDeskStore } from '../../stores/desk'
import { getModule } from '../../composables/workspace/moduleRegistry'
import { useWindowInteractions } from '../../composables/desk/useWindowInteractions'
import type { ResizeEdge } from '../../composables/desk/useWindowInteractions'
import type { DeskWindowState } from '../../composables/desk/deskGeometry'

const props = defineProps<{
  win: DeskWindowState
}>()

const desk = useDeskStore()
const { startDrag, startResize } = useWindowInteractions(props.win.id)

const EDGES: ResizeEdge[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']

const moduleDef = computed(() => getModule(props.win.moduleId))
const title = computed(() => moduleDef.value?.label ?? props.win.moduleId)
const focused = computed(() => desk.focusedId === props.win.id)

// Lazy adapter resolution — PanelLeaf's pattern + retry-then-fail on load
// errors (spec §6.16: a failed chunk must not crash the scene).
const asyncComp = computed(() => {
  const def = moduleDef.value
  if (def === undefined) return null
  return defineAsyncComponent({
    loader: def.component,
    loadingComponent: AliceSpinner,
    errorComponent: {
      render: () =>
        h(UiEmptyState, {
          icon: 'alert-triangle',
          title: 'Modulo non caricato',
          subtitle: 'Chiudi e riapri la finestra',
          compact: true
        })
    },
    onError(_error, retry, fail, attempts) {
      if (attempts <= 2) retry()
      else fail()
    }
  })
})

const styleObj = computed(() => ({
  left: `${props.win.rect.x}px`,
  top: `${props.win.rect.y}px`,
  width: `${props.win.rect.w}px`,
  height: `${props.win.rect.h}px`,
  zIndex: props.win.z + 1
}))

function onWindowPointerDown(): void {
  if (!focused.value) desk.focusWindow(props.win.id)
}
</script>

<template>
  <section
    v-show="!win.minimized"
    class="desk-window"
    :class="{ 'desk-window--focused': focused }"
    :style="styleObj"
    role="region"
    :aria-label="title"
    @pointerdown="onWindowPointerDown"
  >
    <header class="desk-window__header" @pointerdown="startDrag">
      <AppIcon v-if="moduleDef" :name="moduleDef.icon" :size="13" class="desk-window__icon" />
      <span class="desk-window__title">{{ title }}</span>
      <UiIconButton
        label="Riduci nel vassoio"
        size="xs"
        variant="ghost"
        @click="desk.minimizeWindow(win.id)"
      >
        <AppIcon name="minus" :size="12" />
      </UiIconButton>
      <UiIconButton
        label="Chiudi finestra"
        size="xs"
        variant="ghost"
        @click="desk.closeWindow(win.id)"
      >
        <AppIcon name="x" :size="12" />
      </UiIconButton>
    </header>

    <div class="desk-window__body">
      <component :is="asyncComp" v-if="asyncComp" :params="win.params" />
      <UiEmptyState
        v-else
        icon="alert-triangle"
        title="Modulo non disponibile"
        :subtitle="`«${win.moduleId}» non è registrato`"
        compact
      />
    </div>

    <span
      v-for="edge in EDGES"
      :key="edge"
      class="desk-window__grip"
      :class="`desk-window__grip--${edge}`"
      aria-hidden="true"
      @pointerdown="(e) => startResize(edge, e)"
    />
  </section>
</template>

<style scoped>
/* Atelier sheet: theme tokens only (dual-theme by construction). */
.desk-window {
  position: absolute;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-floating);
  overflow: hidden;
  pointer-events: auto;
}

.desk-window--focused {
  border-color: var(--border-hover);
  box-shadow: var(--shadow-elevated);
}

.desk-window__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 34px;
  flex: none;
  padding: 0 var(--space-2);
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
  cursor: grab;
  user-select: none;
  touch-action: none;
}

.desk-window__header:active {
  cursor: grabbing;
}

.desk-window__icon {
  color: var(--text-secondary);
  flex: none;
}

.desk-window__title {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.desk-window__body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.desk-window__body > * {
  flex: 1;
  min-height: 0;
}

/* Resize grips: invisible strips along edges/corners. */
.desk-window__grip {
  position: absolute;
  touch-action: none;
}

.desk-window__grip--n,
.desk-window__grip--s {
  left: 10px;
  right: 10px;
  height: 6px;
  cursor: ns-resize;
}

.desk-window__grip--n {
  top: -3px;
}

.desk-window__grip--s {
  bottom: -3px;
}

.desk-window__grip--e,
.desk-window__grip--w {
  top: 10px;
  bottom: 10px;
  width: 6px;
  cursor: ew-resize;
}

.desk-window__grip--e {
  right: -3px;
}

.desk-window__grip--w {
  left: -3px;
}

.desk-window__grip--ne,
.desk-window__grip--nw,
.desk-window__grip--se,
.desk-window__grip--sw {
  width: 12px;
  height: 12px;
}

.desk-window__grip--ne {
  top: -3px;
  right: -3px;
  cursor: nesw-resize;
}

.desk-window__grip--nw {
  top: -3px;
  left: -3px;
  cursor: nwse-resize;
}

.desk-window__grip--se {
  bottom: -3px;
  right: -3px;
  cursor: nwse-resize;
}

.desk-window__grip--sw {
  bottom: -3px;
  left: -3px;
  cursor: nesw-resize;
}
</style>
