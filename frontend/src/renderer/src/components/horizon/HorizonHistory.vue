<script setup lang="ts">
/**
 * HorizonHistory — the conversation record as an editorial dossier: a left
 * glass drawer aligned to the docked sidebar (same gutters + radius), reading
 * bottom-up. Exchanges (a user prompt and the turns it triggers) are grouped:
 * a hairline opens each exchange, and within one the turns flow without rules.
 * User prompts read as quiet marginalia; AL\CE is the primary voice; tool
 * results are contained receipts, not naked JSON. Mirrors the props/emits
 * contract of the retired orb-era history drawer so the view wiring is a
 * drop-in.
 */
import { computed, nextTick, ref, watch } from 'vue'

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

/**
 * Assistant turns that are pure tool-call carriers (no textual content) render
 * as dead rows — an "AL\CE" rubric over nothing. Drop them: the tool result
 * that follows is the visible record of that step.
 */
const renderedMessages = computed(() =>
  props.messages.filter((m) => !(m.role === 'assistant' && !(m.content ?? '').trim()))
)

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
function truncateContent(text: string, max = 240): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}
</script>

<template>
  <Transition name="hz-drawer">
    <aside v-if="open" class="hz-history" aria-label="Conversazione">
      <header class="hz-history__head">
        <span class="hz-history__title">Conversazione</span>
        <!-- Bespoke (Regola bespoke): content-sized, color-only hover actions —
             the kit's 24px hover square would weigh down this minimal dossier.
             Focus-visible comes from the global ring. -->
        <button class="hz-history__close" aria-label="Chiudi" @click="emit('close')">
          <AppIcon name="x" :size="13" />
        </button>
      </header>

      <div ref="scrollRef" class="hz-history__scroll">
        <article
          v-for="msg in renderedMessages"
          :key="msg.id"
          class="hz-history__entry"
          :class="`hz-history__entry--${msg.role}`"
        >
          <div class="hz-history__rubric">
            <span class="hz-history__role">
              <span class="hz-history__dot" aria-hidden="true" />
              {{ ROLE_LABELS[msg.role] ?? msg.role }}
            </span>
            <span class="hz-history__entry-actions">
              <button
                v-if="msg.role === 'user' && !isStreaming"
                class="hz-history__action"
                aria-label="Modifica"
                @click="emit('edit', msg.id)"
              >
                <AppIcon name="edit" :size="11" />
              </button>
              <button
                v-if="msg.role === 'assistant' && !branchDisabled"
                class="hz-history__action"
                aria-label="Crea ramo"
                @click="emit('branch', msg.id)"
              >
                <AppIcon name="branch" :size="11" />
              </button>
            </span>
          </div>

          <div v-if="msg.role === 'tool'" class="hz-history__tool">
            <div class="hz-history__tool-body">{{ truncateContent(msg.content) }}</div>
          </div>
          <!-- eslint-disable vue/no-v-html -- sanitized markdown render (renderMarkdown uses markdown-it with html:false) -->
          <div
            v-else
            class="hz-history__body markdown-body"
            v-html="renderMarkdown(msg.content ?? '')"
          />
          <!-- eslint-enable vue/no-v-html -->

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
/*
 * Glass drawer. It borrows the docked sidebar's gutters (--gutter-lg) and
 * radius (--panel-radius) so the two panels sit on the same grid — but where
 * the sidebar is a solid in-flow surface, this is a scene overlay: the veil
 * (--glass-*, cfr. UiCard) lets the Horizon scene read through, so the drawer
 * belongs to the scene rather than sitting opaquely on top of it.
 */
.hz-history {
  position: absolute;
  top: var(--gutter-lg);
  left: var(--gutter-lg);
  bottom: var(--gutter-lg);
  width: min(420px, 86vw);
  display: flex;
  flex-direction: column;
  background: var(--glass-bg-light);
  border: 1px solid var(--glass-border);
  border-radius: var(--panel-radius);
  box-shadow: var(--panel-shadow, var(--shadow-md));
  -webkit-backdrop-filter: blur(var(--glass-blur, 12px));
  backdrop-filter: blur(var(--glass-blur, 12px));
  z-index: var(--z-overlay);
  overflow: hidden;
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
  transition: color var(--hz-fade) ease;
}

.hz-history__close:hover {
  color: var(--hz-ink);
}

.hz-history__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-2) var(--space-4) var(--space-4);
  scrollbar-width: thin;
}

/* A turn. Rules only open an exchange (see the user-turn rule below). */
.hz-history__entry {
  padding-block: var(--space-2-5);
}

/* Each user prompt opens a new exchange: a hairline + extra space above,
   except the first rendered turn. Turns inside an exchange just breathe. */
.hz-history__entry--user:not(:first-child) {
  margin-top: var(--space-3);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border);
}

.hz-history__rubric {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-1-5);
}

.hz-history__role {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.22em;
  color: var(--hz-ink-faint);
}

/* AL\CE is the voice — the only rubric that carries the gold. */
.hz-history__entry--assistant .hz-history__role {
  color: var(--hz-gold);
}

.hz-history__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  flex: none;
}

.hz-history__entry-actions {
  display: inline-flex;
  gap: var(--space-1);
}

/* Actions stay out of the way until the turn is hovered. */
.hz-history__action {
  display: inline-flex;
  border: none;
  background: transparent;
  color: var(--hz-ink-faint);
  cursor: pointer;
  opacity: 0;
  transition:
    opacity var(--hz-fade) ease,
    color var(--hz-fade) ease;
}

.hz-history__entry:hover .hz-history__action,
.hz-history__action:focus-visible {
  opacity: 1;
}

.hz-history__action:hover {
  color: var(--hz-ink);
}

.hz-history__body {
  font-family: var(--hz-serif);
  font-weight: 300;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

/* AL\CE — the primary voice: full ink, a touch larger. */
.hz-history__entry--assistant .hz-history__body,
.hz-history__entry--system .hz-history__body {
  font-size: var(--text-md);
  color: var(--hz-ink);
}

/* TU — the prompt, set as quiet marginalia against a hairline rule. */
.hz-history__entry--user .hz-history__body {
  font-size: var(--text-base);
  color: var(--hz-ink-dim);
  border-left: 2px solid var(--accent-dim);
  padding-left: var(--space-3);
}

.hz-history__body :deep(p) {
  margin: 0 0 0.5em;
}

.hz-history__body :deep(p:last-child) {
  margin-bottom: 0;
}

.hz-history__body :deep(pre),
.hz-history__body :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.8em;
}

/* Tool result — a contained receipt: quiet mono on an inset, long dumps
   fade out rather than sprawling. */
.hz-history__tool {
  margin-top: var(--space-2);
  border: 1px solid var(--border);
  background: var(--surface-inset);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.hz-history__tool-body {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--hz-ink-faint);
  padding: var(--space-2) var(--space-2-5);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 88px;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(180deg, #000 62px, transparent);
  mask-image: linear-gradient(180deg, #000 62px, transparent);
}

/* Short slide + fade: a full -100% slide fights the floating-card look. */
.hz-drawer-enter-active,
.hz-drawer-leave-active {
  transition:
    transform var(--hz-fade) var(--ease-out-expo),
    opacity var(--hz-fade) ease;
}

.hz-drawer-enter-from,
.hz-drawer-leave-to {
  transform: translateX(-24px);
  opacity: 0;
}
</style>
