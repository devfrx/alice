<script setup lang="ts">
/**
 * ChatModule — Tiling-leaf adapter for the Chat surface.
 *
 * When the chat is converted into a tile, the leaf renders the real chat via
 * `ChatPanel`, which reuses the existing message thread + composer.
 */
import ChatPanel from '../ChatPanel.vue'

const props = defineProps<{
  params?: Record<string, unknown>
}>()

const conversationId = (props.params?.conversationId as string | undefined) ?? null
</script>

<template>
  <div class="module-root">
    <ChatPanel :conversation-id="conversationId" :embedded="true" />
  </div>
</template>

<style scoped>
.module-root {
  width: 100%;
  height: 100%;
}
</style>
