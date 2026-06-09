<script setup lang="ts">
/**
 * AL\CE — Home ("editorial dossier").
 *
 * A personal, agentic entry surface (not a launcher): time-of-day greeting,
 * a hero composer that starts a REAL turn via useChat().sendMessage, recent
 * conversations to resume, and a runtime colophon. Real signals only.
 */
import { computed, inject, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ChatApiKey } from '../composables/useChat'
import { useChatStore } from '../stores/chat'
import { useMemoryStore } from '../stores/memory'
import { useUIStore } from '../stores/ui'

import HomeGreeting from '../components/home/HomeGreeting.vue'
import HomeComposer from '../components/home/HomeComposer.vue'
import HomeIntents from '../components/home/HomeIntents.vue'
import HomeResume from '../components/home/HomeResume.vue'
import HomeColophon from '../components/home/HomeColophon.vue'

const router = useRouter()
const chatStore = useChatStore()
const memoryStore = useMemoryStore()
const uiStore = useUIStore()
const chatApi = inject(ChatApiKey)

const draft = ref('')
const composerRef = ref<InstanceType<typeof HomeComposer> | null>(null)

const conversationCount = computed(
  () => chatStore.conversations.filter((c) => c.message_count > 0).length
)
const memoryCount = computed(() => memoryStore.stats?.total ?? 0)

/** Navigate into the user's active chat surface (workspace/assistant). */
async function enterActiveSurface(): Promise<void> {
  try {
    await router.push({ name: uiStore.mode })
  } catch (err) {
    console.error('[HomeView] Navigation failed:', err)
  }
}

/** Submit the composer: start a real turn, then enter the active surface. */
async function onSubmit(): Promise<void> {
  const text = draft.value.trim()
  if (!text || !chatApi) return
  draft.value = ''
  await chatApi.sendMessage(text)
  await enterActiveSurface()
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

/** Open a specific conversation, then enter the active surface. */
async function onOpen(id: string): Promise<void> {
  try {
    await chatStore.loadConversation(id)
  } catch (err) {
    console.error(`[HomeView] Failed to load conversation ${id}:`, err)
    return
  }
  await enterActiveSurface()
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
