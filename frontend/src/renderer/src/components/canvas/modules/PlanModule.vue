<script setup lang="ts">
/**
 * PlanModule — Workspace tile showing the active conversation's plan document.
 *
 * ## Param keys (params?: Record<string, unknown>)
 * None consumed. The plan document is per-conversation, so the module derives
 * its subject from the chat store's current conversation rather than tile params.
 *
 * ## Data flow
 * On mount and whenever the conversation changes, the plan document is fetched
 * once via {@link usePlanDocumentStore.ensureForConversation}. Live updates
 * arrive out-of-band through the `plan_document.updated` events-WS frame (folded
 * by the store), so no polling is needed here.
 *
 * ## Rendering
 * The document body is free-form Markdown, rendered to sanitised HTML via
 * {@link renderMarkdown} and shown inside a `.markdown-body` wrapper (the same
 * global stylesheet the chat bubbles use). A `.markdown-body` is the global
 * style class — it lives outside scoped styles, so it is referenced by name only.
 *
 * ## Fallback
 * A {@link UiEmptyState} is rendered until the conversation has a written plan.
 */
import { computed, onMounted, watch } from 'vue'

import UiEmptyState from '../../ui/UiEmptyState.vue'
import { useChatStore } from '@renderer/stores/chat'
import { usePlanDocumentStore } from '@renderer/stores/planDocument'
import { renderMarkdown } from '@renderer/composables/useMarkdown'

defineProps<{
  params?: Record<string, unknown>
}>()

const chatStore = useChatStore()
const planDocumentStore = usePlanDocumentStore()

/** Active conversation id, or null when none is open. */
const conversationId = computed<string | null>(() => chatStore.currentConversation?.id ?? null)

/** Plan document for the active conversation (null when none/empty body). */
const document = computed(() =>
  conversationId.value ? planDocumentStore.documentFor(conversationId.value) : null
)

/** Pre-rendered HTML from the plan document's markdown body. */
const htmlContent = computed(() => renderMarkdown(document.value?.body ?? ''))

/** "aggiornato HH:MM" meta line, or empty when no timestamp is known. */
const updatedLabel = computed<string>(() => {
  const iso = document.value?.updatedAt
  if (!iso) return ''
  const time = new Date(iso).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
  return `aggiornato ${time}`
})

/** Fetch-once the plan document for a given conversation id. */
function load(id: string | null): void {
  if (id) void planDocumentStore.ensureForConversation(id)
}

onMounted(() => load(conversationId.value))
watch(conversationId, (id) => load(id))
</script>

<template>
  <div class="plan-module">
    <template v-if="document">
      <div v-if="updatedLabel" class="plan-module__meta">{{ updatedLabel }}</div>
      <div class="plan-module__scroll">
        <!-- eslint-disable-next-line vue/no-v-html — content is sanitised by markdown-it -->
        <div class="markdown-body" v-html="htmlContent" />
      </div>
    </template>
    <UiEmptyState
      v-else
      icon="file-lines"
      title="Nessun piano scritto."
      subtitle="Il piano comparirà qui quando l'assistente inizierà a scriverlo."
    />
  </div>
</template>

<style scoped>
.plan-module {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Header meta line: "aggiornato HH:MM". */
.plan-module__meta {
  flex-shrink: 0;
  padding: var(--space-2) var(--space-4) 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* Scrollable markdown body fills the height of the tile. */
.plan-module__scroll {
  flex: 1 1 0;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
}
</style>
