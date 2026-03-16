<script setup lang="ts">
/**
 * MessageBubble.vue — Renders a single chat message.
 *
 * User messages are right-aligned with an accent background.
 * Assistant messages are left-aligned with a secondary background
 * and a subtle glow border.  Markdown is rendered via `useMarkdown`.
 * Supports collapsible thinking content and image attachments.
 */
import { computed, ref, watch, onUnmounted } from 'vue'

import { renderMarkdown } from '../../composables/useMarkdown'
import { useCodeBlocks } from '../../composables/useCodeBlocks'
import ThinkingSection from './ThinkingSection.vue'
import ToolCallSection from './ToolCallSection.vue'
import type { ChatMessage } from '../../types/chat'

const props = defineProps<{
  /** The message to render. */
  message: ChatMessage
}>()

/** Pre-rendered HTML from the message's markdown content. */
const htmlContent = computed(() => renderMarkdown(props.message.content))

/** Pre-rendered HTML from the message's thinking content (if any). */
const thinkingHtml = computed(() =>
  props.message.thinking_content ? renderMarkdown(props.message.thinking_content) : ''
)

/** URL of the image shown in the full-size overlay. */
const overlayImageUrl = ref<string | null>(null)

/** Alt text for the overlay image. */
const overlayImageAlt = ref('')

/** Human-readable time string derived from `created_at`. */
const formattedTime = computed(() => {
  try {
    const date = new Date(props.message.created_at)
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return ''
  }
})

/** CSS modifier class based on the message role. */
const bubbleClass = computed(() => `bubble--${props.message.role}`)

const { handleCodeBlockClick } = useCodeBlocks()

/** Open full-size image overlay. */
function openOverlay(url: string, alt: string): void {
  overlayImageUrl.value = url
  overlayImageAlt.value = alt
}

/** Close the full-size image overlay. */
function closeOverlay(): void {
  overlayImageUrl.value = null
  overlayImageAlt.value = ''
}

/** Handle Escape key to close overlay. */
function handleKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && overlayImageUrl.value) {
    closeOverlay()
  }
}

watch(overlayImageUrl, (url) => {
  if (url) {
    window.addEventListener('keydown', handleKeydown)
  } else {
    window.removeEventListener('keydown', handleKeydown)
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="bubble-row" :class="`row--${message.role}`" role="article" :aria-label="`Messaggio ${message.role}`">
    <div class="bubble" :class="bubbleClass">
      <!-- Image attachments -->
      <div v-if="message.attachments?.length" class="bubble__attachments">
        <div v-for="att in message.attachments" :key="att.file_id" class="bubble__attachment" :title="att.filename"
          @click="openOverlay(att.url, att.filename)">
          <img :src="att.url" :alt="att.filename" loading="lazy" />
        </div>
      </div>

      <!-- Thinking section (assistant only) -->
      <ThinkingSection v-if="message.thinking_content" :thinking-html="thinkingHtml" :initial-collapsed="true" />

      <!-- Tool calls section (assistant only) -->
      <ToolCallSection v-if="message.tool_calls?.length" :tool-calls="message.tool_calls ?? []" />

      <!-- Message content -->
      <!-- eslint-disable-next-line vue/no-v-html — content is sanitised by markdown-it -->
      <div class="bubble__content" v-html="htmlContent" @click="handleCodeBlockClick" />
      <span class="bubble__time">{{ formattedTime }}</span>
    </div>

    <!-- Full-size image overlay -->
    <Teleport to="body">
      <div v-if="overlayImageUrl" class="image-overlay" @click.self="closeOverlay">
        <button class="image-overlay__close" aria-label="Chiudi" @click="closeOverlay">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
        <img :src="overlayImageUrl" :alt="overlayImageAlt" class="image-overlay__img" />
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* MessageBubble — Supabase-clean */

/* Row layout */
.bubble-row {
  display: flex;
  margin-bottom: var(--space-4);
  position: relative;
}

.row--user {
  justify-content: flex-end;
}

.row--assistant,
.row--tool {
  justify-content: flex-start;
}

/* Bubble base */
.bubble {
  position: relative;
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  word-break: break-word;
}

/* User bubble */
.bubble--user {
  max-width: 65%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  padding: var(--space-3) var(--space-4);
  line-height: var(--leading-relaxed);
  animation: slideInRight 300ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* Assistant bubble */
.bubble--assistant {
  max-width: 82%;
  background: transparent;
  border: none;
  border-radius: 0;
  padding: var(--space-3) var(--space-4);
  color: var(--text-primary);
  line-height: var(--leading-relaxed);
  animation: slideInLeft 300ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* Tool result bubble */
.bubble--tool {
  max-width: 78%;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  padding: var(--space-3) var(--space-4);
  line-height: var(--leading-relaxed);
  animation: slideInLeft 300ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* Attachments */
.bubble__attachments {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.bubble__attachment {
  width: 144px;
  height: 104px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  cursor: pointer;
  border: 1px solid var(--border);
  transition: border-color var(--transition-fast);
}

.bubble__attachment:hover {
  border-color: var(--accent-border);
}

.bubble__attachment img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

/* Content typography */
.bubble__content {
  overflow-wrap: break-word;
  user-select: text;
  cursor: text;
}

.bubble__content :deep(p) {
  margin: 0 0 0.5em;
}

.bubble__content :deep(p:last-child) {
  margin-bottom: 0;
}

.bubble__content :deep(a) {
  color: var(--accent);
  text-decoration: underline;
  text-decoration-color: var(--accent-border);
  text-underline-offset: 2px;
  transition: text-decoration-color var(--transition-fast);
}

.bubble__content :deep(a:hover) {
  text-decoration-color: var(--accent);
}

.bubble__content :deep(ul),
.bubble__content :deep(ol) {
  padding-left: 1.4em;
  margin: 0.4em 0;
}

.bubble__content :deep(blockquote) {
  border-left: 2px solid var(--border);
  margin: 0.5em 0;
  padding: var(--space-2) var(--space-3);
  color: var(--text-secondary);
}

/* Timestamp — hover to reveal, positioned to the side */
.bubble__time {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  opacity: 0;
  white-space: nowrap;
  pointer-events: none;
  transition: opacity var(--transition-fast);
}

.bubble:hover .bubble__time {
  opacity: 1;
}

.row--user .bubble__time {
  right: calc(100% + var(--space-3));
  left: auto;
}

.row--assistant .bubble__time,
.row--tool .bubble__time {
  left: calc(100% + var(--space-3));
  right: auto;
}

/* Image overlay */
.image-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--black-overlay);
  animation: overlayFadeIn 200ms ease both;
}

.image-overlay__close {
  position: absolute;
  top: var(--space-4);
  right: var(--space-4);
  background: none;
  border: none;
  padding: var(--space-2);
  cursor: pointer;
  color: var(--text-secondary);
  transition: color var(--transition-fast);
}

.image-overlay__close:hover {
  color: var(--text-primary);
}

.image-overlay__img {
  max-width: 90vw;
  max-height: 88vh;
  object-fit: contain;
  border-radius: var(--radius-md);
  animation: overlayZoomIn 250ms ease both;
}

/* Keyframes */
@keyframes slideInRight {
  from {
    opacity: 0;
    transform: translateX(20px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes slideInLeft {
  from {
    opacity: 0;
    transform: translateX(-20px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes bubbleFadeIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

@keyframes overlayFadeIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

@keyframes overlayZoomIn {
  from {
    opacity: 0;
    transform: scale(0.96);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {

  .bubble--user,
  .bubble--assistant,
  .bubble--tool,
  .image-overlay,
  .image-overlay__img {
    animation: none !important;
  }

  .bubble__time,
  .bubble__attachment,
  .image-overlay__close {
    transition: none;
  }
}
</style>
