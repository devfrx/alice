<script setup lang="ts">
/**
 * HorizonHistory — the conversation record as an editorial dossier: a left
 * drawer with role rubrics in mono, serif bodies, hairline rules. Mirrors
 * the props/emits contract of the retired orb-era history drawer so the
 * view wiring is a drop-in.
 */
import { nextTick, ref, watch } from 'vue'

import { renderMarkdown } from '../../composables/useMarkdown'
import MessageVersionNav from '../chat/MessageVersionNav.vue'
import AppIcon from '../ui/AppIcon.vue'
import type { ChatMessage } from '../../types/chat'

const props = defineProps<{
  open: boolean
  messages: ChatMessage[]
  isStreaming: boolean
  branchDisabled: boolean
  getVersionCount: (groupId: string) => number
  getActiveVersionIndex: (groupId: string) => number
}>()

const emit = defineEmits<{
  close: []
  edit: [messageId: string]
  'switch-version': [versionGroupId: string, versionIndex: number]
  branch: [messageId: string]
}>()

const ROLE_LABELS: Record<string, string> = {
  user: 'TU',
  assistant: 'AL\\CE',
  tool: 'STRUMENTO',
  system: 'SISTEMA'
}

const scrollRef = ref<HTMLElement | null>(null)

// Open lands on the newest entry (the conversation reads bottom-up, like
// the legacy drawer).
watch(
  () => props.open,
  async (open) => {
    if (!open) return
    await nextTick()
    if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight
  }
)

/** Tool dumps are capped like the legacy drawer — the dossier is a record, not a log. */
function truncateContent(text: string, max = 200): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}
</script>

<template>
  <Transition name="hz-drawer">
    <aside v-if="open" class="hz-history" aria-label="Conversazione">
      <header class="hz-history__head">
        <span class="hz-history__title">Conversazione</span>
        <button class="hz-history__close" aria-label="Chiudi" @click="emit('close')">
          <AppIcon name="x" :size="13" />
        </button>
      </header>

      <div ref="scrollRef" class="hz-history__scroll">
        <article v-for="msg in messages" :key="msg.id" class="hz-history__entry">
          <div class="hz-history__rubric">
            <span class="hz-history__role">{{ ROLE_LABELS[msg.role] ?? msg.role }}</span>
            <span class="hz-history__entry-actions">
              <button
                v-if="msg.role === 'user' && !isStreaming"
                class="hz-history__action"
                title="Modifica"
                @click="emit('edit', msg.id)"
              >
                <AppIcon name="edit" :size="11" />
              </button>
              <button
                v-if="msg.role === 'assistant' && !branchDisabled"
                class="hz-history__action"
                title="Crea ramo"
                @click="emit('branch', msg.id)"
              >
                <AppIcon name="branch" :size="11" />
              </button>
            </span>
          </div>

          <div v-if="msg.role === 'tool'" class="hz-history__body hz-history__body--tool">
            {{ truncateContent(msg.content) }}
          </div>
          <!-- eslint-disable-next-line vue/no-v-html -->
          <div
            v-else
            class="hz-history__body markdown-body"
            v-html="renderMarkdown(msg.content ?? '')"
          />

          <MessageVersionNav
            v-if="
              msg.role === 'user' &&
              msg.version_group_id &&
              getVersionCount(msg.version_group_id) > 1
            "
            :active-index="getActiveVersionIndex(msg.version_group_id)"
            :total-versions="getVersionCount(msg.version_group_id)"
            :disabled="isStreaming"
            @switch="(i) => emit('switch-version', msg.version_group_id!, i)"
          />
        </article>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.hz-history {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: min(420px, 86vw);
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  z-index: var(--z-overlay);
}

.hz-history__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border);
}

.hz-history__title {
  font-family: var(--hz-serif);
  font-size: var(--text-base);
  font-weight: 300;
  color: var(--hz-ink);
}

.hz-history__close {
  display: inline-flex;
  border: none;
  background: transparent;
  color: var(--hz-ink-dim);
  cursor: pointer;
}

.hz-history__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3) var(--space-4);
  scrollbar-width: thin;
}

.hz-history__entry {
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--border);
}

.hz-history__rubric {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-1-5);
}

.hz-history__role {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.3em;
  color: var(--hz-gold);
}

.hz-history__entry-actions {
  display: inline-flex;
  gap: var(--space-1);
}

.hz-history__action {
  display: inline-flex;
  border: none;
  background: transparent;
  color: var(--hz-ink-faint);
  cursor: pointer;
}

.hz-history__action:hover {
  color: var(--hz-ink);
}

.hz-history__body {
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: var(--text-sm);
  line-height: 1.65;
  color: var(--hz-ink-dim);
  overflow-wrap: anywhere;
}

.hz-history__body--tool {
  font-family: var(--font-mono);
  font-size: 0.8em;
  white-space: pre-wrap;
  opacity: 0.7;
}

.hz-history__body :deep(p) {
  margin: 0 0 0.5em;
}

.hz-history__body :deep(pre),
.hz-history__body :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.8em;
}

.hz-drawer-enter-active,
.hz-drawer-leave-active {
  transition: transform var(--hz-fade) var(--ease-out-expo);
}

.hz-drawer-enter-from,
.hz-drawer-leave-to {
  transform: translateX(-100%);
}
</style>
