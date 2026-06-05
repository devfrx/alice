<script setup lang="ts">
/**
 * WorkspaceView — thin route wrapper mounting the tiling {@link PanelWorkspace}
 * as the primary surface. Passes the active conversation id so the chat panel
 * and artifact auto-open scope to the current conversation.
 */
import { computed } from 'vue'
import PanelWorkspace from '../components/canvas/PanelWorkspace.vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()

const conversationId = computed<string | null>(() => chatStore.currentConversation?.id ?? null)
</script>

<template>
  <div class="workspace-view">
    <PanelWorkspace :conversation-id="conversationId" />
  </div>
</template>

<style scoped>
.workspace-view {
  width: 100%;
  height: 100%;
}
</style>
