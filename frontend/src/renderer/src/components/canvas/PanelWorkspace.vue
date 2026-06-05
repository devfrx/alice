<script setup lang="ts">
/**
 * PanelWorkspace — Top-level tiling-workspace surface.
 *
 * Two presentation modes, driven by `workspaceStore.chatMode`:
 *
 * - 'anchored' (default): chat lives in a dedicated, resizable LEFT column
 *   (`ChatPanel`). When modules are open, a divider + the tiling tree render
 *   beside it; otherwise the chat fills the whole surface.
 * - 'tiled': chat is a leaf inside the tiling tree — only the tree renders
 *   (the chat appears as a normal tile via ChatModule → ChatPanel).
 *
 * The module launcher lives in the ChatPanel header (not as a floating overlay
 * on the workspace). The empty state shows only in the degenerate tiled case
 * (no modules at all).
 */
import { computed, toRef, onMounted, onUnmounted } from 'vue'
import SplitContainer from './SplitContainer.vue'
import PanelLeaf from './PanelLeaf.vue'
import ChatPanel from './ChatPanel.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import { useResizablePane } from '../../composables/useResizablePane'
import { useWorkspaceStore } from '../../stores/workspace'
import { onOpenModule } from '../../composables/workspace/moduleIntents'
import { useArtifactAutoOpen } from '../../composables/workspace/useArtifactAutoOpen'

const props = defineProps<{
  conversationId?: string | null
}>()

const workspaceStore = useWorkspaceStore()

const root = computed(() => workspaceStore.layout.root)
const isAnchored = computed(() => workspaceStore.chatMode === 'anchored')

// Width of the anchored chat column (px). Persist is optional for Phase-1.
const {
  size: chatWidth,
  isDragging: isDraggingChat,
  onMouseDown: onChatResizeStart
} = useResizablePane({ axis: 'x', min: 320, max: 900, initial: 520 })

// DEV-only: keep a single reset affordance for layout testing.
const isDev = import.meta.env.DEV

// ── Intent bus: CONSUMER ──────────────────────────────────────────────────
// Subscribe here (not in the store) so the handler is scoped to this
// component's lifetime and automatically unregistered on unmount — no
// risk of handler accumulation across test-pinia re-instantiations.
let _unsubscribeIntentBus: (() => void) | null = null

onMounted(() => {
  _unsubscribeIntentBus = onOpenModule(({ moduleId, params }) => {
    if (!workspaceStore.autoOpenEnabled) return
    workspaceStore.openModule(moduleId, params)
  })
})

onUnmounted(() => {
  _unsubscribeIntentBus?.()
  _unsubscribeIntentBus = null
})

// ── Intent bus: PRODUCER ──────────────────────────────────────────────────
// Watch for new content and emit open-module intents. Accepts the reactive
// conversation id so the CAD watcher can scope to the active conversation.
useArtifactAutoOpen(toRef(props, 'conversationId'))
</script>

<template>
  <div class="panel-workspace" :class="{ 'panel-workspace--dragging': isDraggingChat }">
    <!-- ── Anchored mode: chat column (+ optional module tree) ── -->
    <template v-if="isAnchored">
      <div
        class="panel-workspace__chat"
        :style="workspaceStore.hasModules && root ? { width: chatWidth + 'px' } : undefined"
        :class="{ 'panel-workspace__chat--solo': !(workspaceStore.hasModules && root) }"
      >
        <ChatPanel :conversation-id="props.conversationId ?? null" />
      </div>

      <template v-if="workspaceStore.hasModules && root">
        <div
          class="panel-workspace__divider"
          :class="{ 'panel-workspace__divider--active': isDraggingChat }"
          @mousedown="onChatResizeStart"
        />
        <div class="panel-workspace__tree">
          <SplitContainer v-if="root.kind === 'split'" :node="root" />
          <PanelLeaf v-else :node="root" />
        </div>
      </template>
    </template>

    <!-- ── Tiled mode: tree only (chat is a leaf) ── -->
    <template v-else>
      <div v-if="workspaceStore.hasModules && root" class="panel-workspace__tree">
        <SplitContainer v-if="root.kind === 'split'" :node="root" />
        <PanelLeaf v-else :node="root" />
      </div>

      <UiEmptyState
        v-else
        icon="hybrid-panel"
        title="Nessun modulo aperto"
        subtitle="Apri un modulo dal pulsante in alto a destra"
      />
    </template>

    <!--
      The module launcher now lives in the ChatPanel header (top-right); no
      floating overlay sits on the workspace content anymore.
      DEV-only: a minimal reset-layout affordance remains, bottom-right.
    -->
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
</template>

<style scoped>
.panel-workspace {
  position: relative;
  display: flex;
  flex-direction: row;
  width: 100%;
  height: 100%;
  /* Matching gutter so the floating sidebar and the workspace surfaces read as
     detached "tabs" with consistent breathing room on every edge. */
  padding: var(--gutter-lg, 10px);
  box-sizing: border-box;
  overflow: hidden;
}

.panel-workspace--dragging {
  cursor: col-resize;
  user-select: none;
}

/* Anchored chat column. */
.panel-workspace__chat {
  position: relative;
  flex-shrink: 0;
  height: 100%;
  min-width: 320px;
  max-width: 900px;
}

.panel-workspace__chat--solo {
  flex: 1;
  width: auto;
  max-width: none;
}

/* Tiling tree area. */
.panel-workspace__tree {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 100%;
}

/* Resizable divider between chat column and tree. */
.panel-workspace__divider {
  width: 6px;
  flex-shrink: 0;
  cursor: col-resize;
  background: transparent;
  transition: background var(--transition-fast);
}

.panel-workspace__divider:hover,
.panel-workspace__divider--active {
  background: var(--accent-border);
}

/* DEV-only reset button — minimal, unobtrusive, bottom-right. */
.panel-workspace__dev-reset {
  position: absolute;
  bottom: var(--space-2, 8px);
  right: var(--space-2, 8px);
  z-index: var(--z-overlay, 50);
  font-size: var(--text-xs, 11px);
  padding: 2px 6px;
  color: var(--text-muted);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  cursor: pointer;
  line-height: 1;
  opacity: 0.6;
}

.panel-workspace__dev-reset:hover {
  color: var(--text-secondary);
  background: var(--surface-hover);
}
</style>
