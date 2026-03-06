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
      <ToolCallSection v-if="message.tool_calls?.length" :tool-calls="message.tool_calls" />

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
  padding: var(--space-2-5) 14px;
  line-height: var(--leading-loose);
  font-size: var(--text-md);
  position: relative;
  word-break: break-word;
}

/* ------------------------------------------------------------- User bubble */
.bubble--user {
  max-width: 65%;
  background: linear-gradient(135deg, var(--accent-light), var(--accent-faint));
  border: 1px solid var(--accent-medium);
  border-radius: 16px 16px var(--radius-sm) 16px;
  color: var(--text-primary);
  animation: slideInUser 0.35s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

/* --------------------------------------------------------- Assistant bubble */
.bubble--assistant {
  max-width: 82%;
  background: transparent;
  border: none;
  border-left: 3px solid var(--accent-medium);
  border-radius: 0;
  padding: var(--space-3) 14px var(--space-3) var(--space-4);
  color: var(--text-primary);
  animation: slideInAssistant 0.35s cubic-bezier(0.16, 1, 0.3, 1) both;
  transition: border-left-color var(--transition-fast);
}

.bubble--assistant:hover {
  border-left-color: var(--accent-border);
}

/* ------------------------------------------------------------- Tool bubble */
.bubble--tool {
  max-width: 78%;
  background: var(--bg-tool);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-muted);
  animation: slideInAssistant 0.35s ease-out both;
}

/* -------------------------------------------------------- Attachments */
.bubble__attachments {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1-5);
  margin-bottom: var(--space-2);
}

.bubble__attachment {
  width: 140px;
  height: 100px;
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: pointer;
  border: 1px solid var(--border);
  transition: border-color var(--transition-fast);
}

.bubble__attachment:hover {
  border-color: var(--accent);
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
  margin-top: 5px;
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.bubble:hover .bubble__time {
  opacity: 1;
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
  background: var(--black-overlay);
  backdrop-filter: blur(var(--blur-md));
  -webkit-backdrop-filter: blur(var(--blur-md));
  animation: fadeIn 0.2s ease;
}

.image-overlay__close {
  position: absolute;
  top: 16px;
  right: 16px;
  background: var(--white-medium);
  border: 1px solid var(--white-strong);
  border-radius: var(--radius-full);
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-primary);
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.image-overlay__close:hover {
  background: var(--white-heavy);
  border-color: var(--white-dim);
}

.image-overlay__img {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
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
    transform: translateY(12px) scale(0.98);
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
