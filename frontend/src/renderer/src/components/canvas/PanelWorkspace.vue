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
import { useWorkspaceStore } from '../../stores/workspace'

defineProps<{
  conversationId?: string | null
}>()

const workspaceStore = useWorkspaceStore()

const root = computed(() => workspaceStore.layout.root)

// TEMP / DEV-ONLY: manual-testing scaffolding. Replaced by the real
// ModuleLauncher in T7. Gated behind import.meta.env.DEV so it never ships in
// production builds.
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

    <!-- TEMP / DEV-ONLY debug bar — remove once ModuleLauncher (T7) lands. -->
    <div v-if="isDev" class="panel-workspace__debug">
      <button type="button" @click="workspaceStore.openModule('chart')">+ chart</button>
      <button type="button" @click="workspaceStore.openModule('whiteboard')">+ whiteboard</button>
      <button type="button" @click="workspaceStore.openModule('cad3d')">+ 3d</button>
      <button type="button" @click="workspaceStore.resetLayout()">reset</button>
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

/* TEMP / DEV-ONLY debug bar styling. */
.panel-workspace__debug {
  position: absolute;
  top: var(--space-2, 8px);
  right: var(--space-2, 8px);
  z-index: var(--z-overlay, 50);
  display: flex;
  gap: var(--space-1, 4px);
  padding: var(--space-1, 4px);
  background: var(--surface-2, rgba(0, 0, 0, 0.4));
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
}

.panel-workspace__debug button {
  font-size: var(--text-xs, 11px);
  padding: 2px 6px;
  color: var(--text-secondary);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  cursor: pointer;
}

.panel-workspace__debug button:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}
</style>
