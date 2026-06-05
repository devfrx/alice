<script setup lang="ts">
/**
 * PanelLeaf — Renders a single leaf tile's module inside a ModulePanel.
 *
 * Resolves the module from the registry, lazily loads its adapter SFC, and
 * forwards `node.params`. Falls back to an empty state when the module id is
 * not registered.
 */
import { computed, defineAsyncComponent } from 'vue'
import ModulePanel from './ModulePanel.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import AliceSpinner from '../ui/AliceSpinner.vue'
import { useWorkspaceStore } from '../../stores/workspace'
import { getModule } from '../../composables/workspace/moduleRegistry'
import type { LeafNode } from '../../composables/workspace/tilingTypes'

const props = defineProps<{
  node: LeafNode
}>()

const workspaceStore = useWorkspaceStore()

const moduleDef = computed(() => getModule(props.node.moduleId))

// Lazily resolve the adapter SFC. defineAsyncComponent must be created with a
// stable factory, so derive it once from the resolved module via computed and
// guard the not-found case in the template.
const asyncComp = computed(() => {
  const def = moduleDef.value
  if (def === undefined) return null
  return defineAsyncComponent({
    loader: def.component,
    loadingComponent: AliceSpinner
  })
})

const isActive = computed<boolean>(() => workspaceStore.activeLeaf?.id === props.node.id)

function onClose(): void {
  workspaceStore.closeLeaf(props.node.id)
}
</script>

<template>
  <ModulePanel
    v-if="moduleDef && asyncComp"
    :title="moduleDef.label"
    :icon="moduleDef.icon"
    :active="isActive"
    @close="onClose"
  >
    <component :is="asyncComp" :params="node.params" />
  </ModulePanel>
  <ModulePanel v-else title="Modulo" :active="isActive" @close="onClose">
    <UiEmptyState
      icon="alert-triangle"
      title="Modulo non disponibile"
      :subtitle="`«${node.moduleId}» non è registrato`"
      compact
    />
  </ModulePanel>
</template>
