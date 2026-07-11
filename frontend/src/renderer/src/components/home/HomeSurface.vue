<script setup lang="ts">
/**
 * HomeSurface — AL\CE's "editorial dossier" entry surface.
 *
 * This is NOT a route: it is the empty-conversation state of the Workspace.
 * {@link WorkspaceView} renders it whenever the active conversation has no
 * messages, and cross-fades it into the live chat the instant a turn starts —
 * so there is no page navigation, just a seamless hand-off on the same surface.
 *
 * Because the swap is driven purely by the conversation becoming non-empty,
 * this component owns no navigation: it only starts a real turn (or reopens a
 * conversation) and lets the parent react. Real signals only.
 */
import { computed, inject, nextTick, ref } from 'vue'

import { ChatApiKey } from '../../composables/useChat'
import { useChatStore } from '../../stores/chat'
import { useMemoryStore } from '../../stores/memory'

import HomeGreeting from './HomeGreeting.vue'
import HomeComposer from './HomeComposer.vue'
import HomeIntents from './HomeIntents.vue'
import HomeResume from './HomeResume.vue'
import HomeColophon from './HomeColophon.vue'

const chatStore = useChatStore()
const memoryStore = useMemoryStore()
const chatApi = inject(ChatApiKey, null)

const draft = ref('')
const composerRef = ref<InstanceType<typeof HomeComposer> | null>(null)

const conversationCount = computed(
  () => chatStore.conversations.filter((c) => c.message_count > 0).length
)
const memoryCount = computed(() => memoryStore.stats?.total ?? 0)

/**
 * Submit the composer: start a real turn. No navigation — pushing the user
 * message flips the conversation to non-empty, and the parent Workspace
 * cross-fades from this surface into the live chat.
 */
async function onSubmit(): Promise<void> {
  const text = draft.value.trim()
  if (!text || !chatApi) return
  draft.value = ''
  await chatApi.sendMessage(text)
}

/** Prefill the composer from an intent chip and focus it. */
function onPrefill(text: string): void {
  draft.value = text
  void nextTick(() => composerRef.value?.focus())
}

/** Reopen the most recent non-empty conversation. */
async function onResumeLast(): Promise<void> {
  const last = [...chatStore.conversations]
    .filter((c) => c.message_count > 0)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0]
  if (last) await onOpen(last.id)
}

/**
 * Open a specific conversation. Loading it fills the message list, which the
 * parent Workspace observes to reveal the chat — again, no navigation here.
 */
async function onOpen(id: string): Promise<void> {
  try {
    await chatStore.loadConversation(id)
  } catch (err) {
    console.error(`[HomeSurface] Failed to load conversation ${id}:`, err)
  }
}
</script>

<template>
  <div class="home">
    <div class="home__atmosphere" aria-hidden="true" />
    <div class="home__stage">
      <main class="home__page">
        <HomeGreeting :conversation-count="conversationCount" :memory-count="memoryCount" />
        <HomeComposer ref="composerRef" v-model="draft" @submit="onSubmit" />
        <HomeIntents @prefill="onPrefill" @resume-last="onResumeLast" />
        <HomeResume :conversations="chatStore.conversations" @open="onOpen" />
        <HomeColophon />
      </main>
    </div>
  </div>
</template>

<style scoped>
.home {
  position: relative;
  width: 100%;
  height: 100%;
  overflow-y: auto;
  background: var(--surface-0);
  color: var(--text-primary);
}

/* Ambient depth — two faint warm sources, top-right + bottom-left. */
.home__atmosphere {
  position: absolute;
  inset: 0;
  z-index: var(--z-base);
  pointer-events: none;
  background:
    radial-gradient(68% 52% at 84% 6%, var(--accent-glow), transparent 60%),
    radial-gradient(72% 60% at 10% 104%, var(--accent-faint), transparent 58%);
}

/* Center the editorial column in the viewport; scroll only when taller. */
.home__stage {
  position: relative;
  z-index: var(--z-raised);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-height: 100%;
  padding: var(--space-12) var(--space-8) var(--space-14);
}

.home__page {
  width: min(720px, 100%);
}

@media (max-width: 680px) {
  .home__stage {
    justify-content: flex-start;
    padding: var(--space-10) var(--space-5) var(--space-10);
  }
}
</style>
