<!-- components/desk/DeskSurface.vue -->
<script setup lang="ts">
/**
 * DeskSurface — the windows layer of the Horizon desk. Renders every desk
 * window, measures the viewport for geometry clamping, and (while mounted)
 * consumes open-module intents — the same bus PanelWorkspace consumes on
 * /workspace; the two surfaces live on different routes so exactly one
 * subscriber is active at a time.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import DeskWindow from './DeskWindow.vue'
import { useDeskStore } from '../../stores/desk'
import { onOpenModule } from '../../composables/workspace/moduleIntents'

const desk = useDeskStore()
const surfaceEl = ref<HTMLElement | null>(null)

let unsubscribe: (() => void) | null = null
let observer: ResizeObserver | null = null

onMounted(() => {
  unsubscribe = onOpenModule((intent) => {
    desk.openWindow(intent.moduleId, intent.params)
  })
  if (surfaceEl.value !== null) {
    observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect
      if (box !== undefined) desk.setViewport(Math.round(box.width), Math.round(box.height))
    })
    observer.observe(surfaceEl.value)
  }
})

onBeforeUnmount(() => {
  unsubscribe?.()
  observer?.disconnect()
})
</script>

<template>
  <div
    ref="surfaceEl"
    class="desk-surface"
    :class="{ 'desk-surface--interacting': desk.draggingId !== null }"
  >
    <DeskWindow v-for="w in desk.windows" :key="w.id" :win="w" />
  </div>
</template>

<style scoped>
.desk-surface {
  position: absolute;
  inset: 0;
  z-index: 4; /* above the scene zones (1-3), below the dock and overlays */
  pointer-events: none; /* windows re-enable their own */
}

.desk-surface--interacting {
  user-select: none;
}
</style>
