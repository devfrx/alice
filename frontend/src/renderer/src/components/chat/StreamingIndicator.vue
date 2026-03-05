<script setup lang="ts">
/**
 * StreamingIndicator.vue — Shows the in-progress assistant response.
 *
 * Renders partial markdown as it streams in, styled identically to an
 * assistant {@link MessageBubble} but with a blinking cursor appended.
 * Includes a collapsible "Ragionamento" section for thinking tokens.
 * The parent controls visibility (`v-if="isStreaming"` outside).
 */
import { computed } from 'vue'

import { renderMarkdown } from '../../composables/useMarkdown'
import { useCodeBlocks } from '../../composables/useCodeBlocks'
import ThinkingSection from './ThinkingSection.vue'

const props = defineProps<{
  /** Accumulated tokens so far (`currentStreamContent` from the store). */
  content: string
  /** Accumulated thinking tokens (`currentThinkingContent` from the store). */
  thinkingContent: string
}>()

/** Rendered HTML of the partial markdown content. */
const htmlContent = computed(() => renderMarkdown(props.content))

/** Rendered HTML of the thinking content. */
const thinkingHtml = computed(() => renderMarkdown(props.thinkingContent))

const { handleCodeBlockClick } = useCodeBlocks()
</script>

<template>
  <div class="bubble-row row--assistant">
    <div class="streaming-bubble">
      <!-- Thinking-only state indicator -->
      <div v-if="thinkingContent && !content" class="streaming-bubble__thinking-state">
        <svg class="streaming-bubble__brain-icon" width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z" />
          <line x1="9" y1="21" x2="15" y2="21" />
          <line x1="10" y1="23" x2="14" y2="23" />
        </svg>
        <span class="streaming-bubble__thinking-label">Ragionamento in corso...</span>
      </div>

      <!-- Thinking section -->
      <ThinkingSection v-if="thinkingContent" :thinking-html="thinkingHtml" :initial-collapsed="true"
        :content-length="thinkingContent.length">
        <span v-if="!content" class="streaming-bubble__cursor" />
      </ThinkingSection>

      <!-- Main content -->
      <Transition name="content-fade">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div v-if="content" class="streaming-bubble__content" v-html="htmlContent" @click="handleCodeBlockClick" />
      </Transition>
      <span v-if="content || !thinkingContent" class="streaming-bubble__cursor" />
    </div>
  </div>
</template>

<style scoped>
.bubble-row {
  display: flex;
  justify-content: flex-start;
  margin-bottom: 12px;
}

.streaming-bubble {
  max-width: 75%;
  padding: 10px 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg) var(--radius-lg) var(--radius-lg) var(--radius-sm);
  box-shadow: 0 0 16px var(--accent-glow);
  color: var(--text-primary);
  line-height: 1.55;
  font-size: 0.9rem;
  word-break: break-word;
  position: relative;
  animation: pulseGlow 2.5s ease-in-out infinite;
}

/* ----- Thinking section — now rendered by ThinkingSection.vue */

/* ----- markdown content */
.streaming-bubble__content :deep(p) {
  margin: 0 0 0.4em;
}

.streaming-bubble__content :deep(p:last-child) {
  margin-bottom: 0;
}

.streaming-bubble__content :deep(a) {
  color: var(--accent);
  text-decoration: underline;
}

/* ----- Code block styles are in assets/styles/code-blocks.css */

/* ------------------------------------------------------ Thinking state */
.streaming-bubble__thinking-state {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.streaming-bubble__brain-icon {
  color: var(--accent);
  opacity: 0.8;
  animation: brainPulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
  flex-shrink: 0;
}

.streaming-bubble__thinking-label {
  font-size: 0.78rem;
  font-style: italic;
  color: var(--accent);
  opacity: 0.7;
  animation: thinkingFade 2s ease-in-out infinite;
}

/* ------------------------------------------------------ Blinking cursor */
.streaming-bubble__cursor {
  display: inline-block;
  width: 3px;
  height: 1em;
  background: linear-gradient(180deg, var(--accent), var(--accent-hover));
  margin-left: 2px;
  vertical-align: text-bottom;
  border-radius: 1px;
  animation: blink 0.8s step-end infinite, cursorFadeIn 0.3s ease both;
}

/* ------------------------------------------------- Content transition */
.content-fade-enter-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.content-fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

@keyframes blink {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}

@keyframes cursorFadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes thinkingFade {
  0%, 100% {
    opacity: 0.7;
  }
  50% {
    opacity: 0.3;
  }
}

@keyframes brainPulse {
  0%, 100% {
    opacity: 0.8;
    transform: scale(1);
  }
  50% {
    opacity: 0.4;
    transform: scale(0.92);
  }
}

@keyframes pulseGlow {
  0%, 100% {
    box-shadow: 0 0 16px var(--accent-glow);
  }
  50% {
    box-shadow: 0 0 24px rgba(201, 168, 76, 0.14);
  }
}
</style>
