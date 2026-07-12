<script setup lang="ts">
/**
 * WorkspaceView — the primary surface.
 *
 * Two states, swapped on the SAME route so the hand-off is seamless (no page
 * navigation, just a cross-fade):
 *
 * - **Empty conversation** → the editorial-dossier {@link HomeSurface}: the
 *   personal entry point. Sending a message (or opening a conversation) fills
 *   the message list, which flips this surface to…
 * - **Active conversation** → the tiling {@link PanelWorkspace} (chat column +
 *   optional module tree), scoped to the current conversation.
 *
 * This is what makes the Home "the page shown when a conversation is empty":
 * it is a state of the workspace, not a separate destination.
 */
import { computed } from 'vue'
import PanelWorkspace from '../components/canvas/PanelWorkspace.vue'
import HomeSurface from '../components/home/HomeSurface.vue'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()

const conversationId = computed<string | null>(() => chatStore.currentConversation?.id ?? null)

/**
 * Show the Home surface while the active conversation holds no messages and is
 * not mid-stream. The first optimistic user message flips this to `false`
 * synchronously, so the transition fires the instant the turn begins.
 */
const showHome = computed<boolean>(
  () => chatStore.messages.length === 0 && !chatStore.isStreamingCurrentConversation
)
</script>

<template>
  <div class="workspace-view">
    <Transition name="ws-surface">
      <HomeSurface v-if="showHome" key="home" />
      <PanelWorkspace v-else key="panel" :conversation-id="conversationId" />
    </Transition>
  </div>
</template>

<style scoped>
.workspace-view {
  position: relative;
  width: 100%;
  height: 100%;
}

/*
 * Cross-fade between the two surfaces. The leaving surface is taken out of
 * flow (absolute, full-bleed) so the entering one occupies the space at once —
 * the two overlap and dissolve rather than one waiting for the other. The slight
 * vertical drift reads as "rising into the work" on send, and reverses on reset.
 */
.ws-surface-enter-active {
  transition:
    opacity var(--duration-slow, 450ms) var(--ease-out-expo),
    transform var(--duration-slow, 450ms) var(--ease-out-expo);
}

.ws-surface-leave-active {
  position: absolute;
  inset: 0;
  transition:
    opacity var(--duration-base, 300ms) var(--ease-smooth),
    transform var(--duration-base, 300ms) var(--ease-smooth);
}

.ws-surface-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.ws-surface-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (prefers-reduced-motion: reduce) {
  .ws-surface-enter-active,
  .ws-surface-leave-active {
    transition: opacity var(--duration-fast) linear;
  }

  .ws-surface-enter-from,
  .ws-surface-leave-to {
    transform: none;
  }
}
</style>
