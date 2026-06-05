<script setup lang="ts">
/**
 * PanelWorkspace — Top-level tiling-workspace surface.
 *
 * Renders the layout tree (split/leaf) when modules are open, otherwise an
 * empty state. The chat surface is anchored in a later task (T9); this
 * component intentionally does NOT build chat.
 */
import { computed } from 'vue'
import SplitContainer from './SplitContainer.vue'
import PanelLeaf from './PanelLeaf.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import ModuleLauncher from './ModuleLauncher.vue'
import { useWorkspaceStore } from '../../stores/workspace'

const props = defineProps<{
  conversationId?: string | null
}>()

const workspaceStore = useWorkspaceStore()

const root = computed(() => workspaceStore.layout.root)

// DEV-only: keep a single reset affordance for layout testing.
const isDev = import.meta.env.DEV
</script>

<template>
  <div class="panel-workspace">
    <template v-if="workspaceStore.hasModules && root">
      <SplitContainer v-if="root.kind === 'split'" :node="root" />
      <PanelLeaf v-else :node="root" />
    </template>

    <UiEmptyState
      v-else
      icon="hybrid-panel"
      title="Nessun modulo aperto"
      subtitle="Apri un modulo dal pulsante in alto a destra"
    />

    <!-- Module launcher — always visible, floats top-right above panel content. -->
    <div class="panel-workspace__toolbar">
      <ModuleLauncher :conversation-id="props.conversationId ?? null" />
      <!-- DEV-only: reset layout button. -->
      <button
        v-if="isDev"
        type="button"
        class="panel-workspace__dev-reset"
        title="Reset layout (DEV)"
        @click="workspaceStore.resetLayout()"
      >
        ↺
      </button>
    </div>
  </div>
</template>

<style scoped>
.panel-workspace {
  position: relative;
  width: 100%;
  height: 100%;
  padding: var(--gutter, 6px);
  box-sizing: border-box;
  overflow: hidden;
}

/* Launcher toolbar — floats top-right above all panel content. */
.panel-workspace__toolbar {
  position: absolute;
  top: var(--space-2, 8px);
  right: var(--space-2, 8px);
  z-index: var(--z-overlay, 50);
  display: flex;
  align-items: center;
  gap: var(--space-1, 4px);
}

/* DEV-only reset button — minimal, unobtrusive. */
.panel-workspace__dev-reset {
  font-size: var(--text-xs, 11px);
  padding: 2px 6px;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  cursor: pointer;
  line-height: 1;
}

.panel-workspace__dev-reset:hover {
  color: var(--text-secondary);
  background: var(--surface-hover);
}
</style>
