<script setup lang="ts">
/**
 * SplitContainer — Recursively renders a binary SplitNode.
 *
 * Measures its own element along the split's main axis with a ResizeObserver
 * and forwards that px extent to the PaneDivider so a drag can be converted
 * into a parent-relative ratio. Each child is rendered as another
 * SplitContainer (split) or a PanelLeaf (leaf).
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import PaneDivider from './PaneDivider.vue'
import PanelLeaf from './PanelLeaf.vue'
import { useWorkspaceStore } from '../../stores/workspace'
import type { SplitNode } from '../../composables/workspace/tilingTypes'

defineOptions({ name: 'SplitContainer' })

const props = defineProps<{
  node: SplitNode
}>()

const workspaceStore = useWorkspaceStore()

const rootEl = ref<HTMLElement | null>(null)
const measuredSize = ref<number>(0)

const isHorizontal = computed<boolean>(() => props.node.orientation === 'horizontal')

let observer: ResizeObserver | null = null

function measure(): void {
  const el = rootEl.value
  if (el === null) return
  measuredSize.value = isHorizontal.value ? el.clientWidth : el.clientHeight
}

onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && rootEl.value) {
    observer = new ResizeObserver(() => measure())
    observer.observe(rootEl.value)
  }
})

onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect()
    observer = null
  }
})

const firstBasis = computed<string>(() => `${props.node.ratio * 100}%`)

function onRatio(r: number): void {
  workspaceStore.setRatio(props.node.id, r)
}
</script>

<template>
  <div
    ref="rootEl"
    class="split-container"
    :class="isHorizontal ? 'split-container--row' : 'split-container--col'"
  >
    <!-- First child -->
    <div
      class="split-container__pane split-container__pane--first"
      :style="{ flexBasis: firstBasis }"
    >
      <SplitContainer v-if="node.children[0].kind === 'split'" :node="node.children[0]" />
      <PanelLeaf v-else :node="node.children[0]" />
    </div>

    <!-- Divider -->
    <PaneDivider
      :orientation="node.orientation"
      :ratio="node.ratio"
      :container-size="measuredSize"
      @update:ratio="onRatio"
    />

    <!-- Second child -->
    <div class="split-container__pane split-container__pane--second">
      <SplitContainer v-if="node.children[1].kind === 'split'" :node="node.children[1]" />
      <PanelLeaf v-else :node="node.children[1]" />
    </div>
  </div>
</template>

<style scoped>
.split-container {
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
}

.split-container--row {
  flex-direction: row;
}

.split-container--col {
  flex-direction: column;
}

.split-container__pane {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.split-container__pane--first {
  flex: 0 0 auto;
}

.split-container__pane--second {
  flex: 1 1 0;
}
</style>
