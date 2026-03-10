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
/* ------------------------------------------------------------------ Row */
.bubble-row {
  display: flex;
  margin-bottom: var(--space-4);
}

.row--user {
  justify-content: flex-end;
}

.row--assistant,
.row--tool {
  justify-content: flex-start;
}

/* ------------------------------------------------------------- Bubble base */
.bubble {
  padding: var(--space-3) var(--space-4);
  line-height: var(--leading-loose);
  font-size: var(--text-md);
  position: relative;
  word-break: break-word;
}

/* ------------------------------------------------------------- User bubble */
.bubble--user {
  max-width: 65%;
  background: linear-gradient(135deg, rgba(201, 168, 76, 0.14), rgba(201, 168, 76, 0.06));
  border: 1px solid rgba(201, 168, 76, 0.18);
  border-radius: 18px 18px var(--radius-sm) 18px;
  color: var(--text-primary);
  box-shadow:
    0 2px 12px rgba(0, 0, 0, 0.2),
    0 0 0 1px rgba(201, 168, 76, 0.05);
  animation: slideInUser 0.35s cubic-bezier(0.34, 1.56, 0.64, 1) both;
  transition: box-shadow var(--transition-fast), transform var(--transition-fast);
}

.bubble--user:hover {
  box-shadow:
    0 4px 16px rgba(0, 0, 0, 0.25),
    0 0 20px rgba(201, 168, 76, 0.06);
  transform: translateY(-1px);
}

/* --------------------------------------------------------- Assistant bubble */
.bubble--assistant {
  max-width: 82%;
  background: transparent;
  border: none;
  border-left: 3px solid var(--accent-medium);
  border-radius: 0;
  padding: var(--space-3) var(--space-4) var(--space-3) var(--space-5);
  color: var(--text-primary);
  animation: slideInAssistant 0.35s cubic-bezier(0.16, 1, 0.3, 1) both;
  transition: border-left-color var(--transition-fast), background var(--transition-fast);
}

.bubble--assistant:hover {
  border-left-color: var(--accent-border);
  background: rgba(255, 255, 255, 0.015);
}

/* ------------------------------------------------------------- Tool bubble */
.bubble--tool {
  max-width: 78%;
  background: rgba(30, 34, 42, 0.5);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius-md);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-muted);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  animation: slideInAssistant 0.35s ease-out both;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.bubble--tool:hover {
  background: rgba(30, 34, 42, 0.65);
  border-color: rgba(255, 255, 255, 0.08);
}

/* -------------------------------------------------------- Attachments */
.bubble__attachments {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-2-5);
}

.bubble__attachment {
  width: 140px;
  height: 100px;
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  transition: border-color var(--transition-fast), transform var(--transition-fast), box-shadow var(--transition-fast);
}

.bubble__attachment:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3), 0 0 12px rgba(201, 168, 76, 0.1);
}

.bubble__attachment img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* --------------------------------------------------------- Content */
.bubble__content {
  overflow-wrap: break-word;
  user-select: text;
  cursor: text;
}

.bubble__content :deep(p) {
  margin: 0 0 0.45em;
}

.bubble__content :deep(p:last-child) {
  margin-bottom: 0;
}

.bubble__content :deep(a) {
  color: var(--accent);
  text-decoration: underline;
  text-decoration-color: rgba(201, 168, 76, 0.3);
  text-underline-offset: 2px;
  transition: text-decoration-color var(--transition-fast);
}

.bubble__content :deep(a:hover) {
  text-decoration-color: var(--accent);
}

/* ----- Code block styles are in assets/styles/code-blocks.css */

.bubble__content :deep(ul),
.bubble__content :deep(ol) {
  padding-left: 1.4em;
  margin: 0.3em 0;
}

.bubble__content :deep(blockquote) {
  border-left: 3px solid var(--accent);
  margin: 0.5em 0;
  padding: 0.25em 0.8em;
  color: var(--text-secondary);
}

/* --------------------------------------------------------- Timestamp */
.bubble__time {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-top: 6px;
  opacity: 0;
  letter-spacing: 0.03em;
  transition: opacity var(--transition-fast);
}

.bubble:hover .bubble__time {
  opacity: 0.7;
}

.row--user .bubble__time {
  text-align: right;
}

.row--assistant .bubble__time,
.row--tool .bubble__time {
  text-align: left;
}

/* ------------------------------------------------- Image overlay */
.image-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  animation: fadeIn 0.25s ease;
}

.image-overlay__close {
  position: absolute;
  top: 16px;
  right: 16px;
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: var(--radius-full);
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-primary);
  transition: background var(--transition-fast), border-color var(--transition-fast), transform var(--transition-fast);
}

.image-overlay__close:hover {
  background: rgba(255, 255, 255, 0.14);
  border-color: rgba(255, 255, 255, 0.2);
  transform: scale(1.05);
}

.image-overlay__img {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: var(--radius-md);
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.5),
    0 0 0 1px rgba(255, 255, 255, 0.06);
  animation: overlayZoomIn 0.3s cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* ------------------------------------------------------------- Keyframes */
@keyframes slideInUser {
  from {
    opacity: 0;
    transform: translateX(14px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes slideInAssistant {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.98);
  }

  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes fadeIn {
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
    transform: scale(0.92);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}

/* ------------------------------------------------- Reduced motion */
@media (prefers-reduced-motion: reduce) {

  .bubble--user,
  .bubble--assistant,
  .bubble--tool {
    animation: none;
  }

  .bubble--user:hover {
    transform: none;
  }

  .image-overlay {
    animation: none;
  }

  .image-overlay__img {
    animation: none;
  }

  .bubble__time,
  .bubble--assistant,
  .bubble__attachment,
  .image-overlay__close {
    transition: none;
  }
}
</style>
