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
import { useChatStore } from '../../stores/chat'
import ThinkingSection from './ThinkingSection.vue'
import ToolExecutionIndicator from './ToolExecutionIndicator.vue'

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

const chatStore = useChatStore()
</script>

<template>
  <div class="bubble-row row--assistant">
    <div class="streaming-bubble">
      <!-- Thinking-only state indicator -->
      <div v-if="thinkingContent && !content" class="streaming-bubble__thinking-state">
        <svg class="streaming-bubble__brain-icon" width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path
            d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z" />
          <line x1="9" y1="21" x2="15" y2="21" />
          <line x1="10" y1="23" x2="14" y2="23" />
        </svg>
        <span class="streaming-bubble__thinking-label">Ragionamento in corso...</span>
      </div>

      <!-- Thinking section -->
      <ThinkingSection v-if="thinkingContent" :thinking-html="thinkingHtml" :initial-collapsed="true"
        :auto-expand="true" :content-length="thinkingContent.length">
        <span v-if="!content" class="streaming-bubble__cursor" />
      </ThinkingSection>

      <!-- Tool execution indicator -->
      <ToolExecutionIndicator :executions="chatStore.activeToolExecutions" />

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
  margin-bottom: var(--space-4);
}

.streaming-bubble {
  max-width: 82%;
  padding: var(--space-3) 14px var(--space-3) var(--space-4);
  background: transparent;
  border: none;
  border-left: 3px solid var(--accent-medium);
  border-radius: 0;
  color: var(--text-primary);
  line-height: var(--leading-relaxed);
  font-size: var(--text-md);
  word-break: break-word;
  position: relative;
  animation: borderPulse 2.5s ease-in-out infinite;
}

/* ----- Thinking section — now rendered by ThinkingSection.vue */

/* ----- markdown content */
.streaming-bubble__content {
  user-select: text;
  cursor: text;
}

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
  gap: var(--space-1-5);
  margin-bottom: var(--space-1-5);
}

.streaming-bubble__brain-icon {
  color: var(--accent);
  opacity: var(--opacity-visible);
  animation: brainPulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
  flex-shrink: 0;
}

.streaming-bubble__thinking-label {
  font-size: var(--text-sm);
  font-style: italic;
  color: var(--accent);
  opacity: var(--opacity-medium);
  animation: thinkingFade 2s ease-in-out infinite;
}

/* ------------------------------------------------------ Blinking cursor */
.streaming-bubble__cursor {
  display: inline-block;
  width: 3px;
  height: 1em;
  background: linear-gradient(180deg, var(--accent), var(--accent-hover));
  margin-left: var(--space-0-5);
  vertical-align: text-bottom;
  border-radius: 1px;
  animation: blink 0.8s step-end infinite, cursorFadeIn 0.3s ease both;
}

/* ------------------------------------------------- Content transition */
.content-fade-enter-active {
  transition: opacity var(--transition-normal), transform var(--transition-normal);
}

.content-fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

@keyframes blink {

  0%,
  100% {
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

  0%,
  100% {
    opacity: 0.7;
  }

  50% {
    opacity: 0.3;
  }
}

@keyframes brainPulse {

  0%,
  100% {
    opacity: 0.8;
    transform: scale(1);
  }

  50% {
    opacity: 0.4;
    transform: scale(0.92);
  }
}

@keyframes borderPulse {

  0%,
  100% {
    border-left-color: var(--accent-medium);
  }

  50% {
    border-left-color: rgba(201, 168, 76, 0.45);
  }
}

/* ------------------------------------------------- Reduced motion */
@media (prefers-reduced-motion: reduce) {
  .streaming-bubble {
    animation: none;
  }

  .streaming-bubble__brain-icon,
  .streaming-bubble__thinking-label {
    animation: none;
  }

  .streaming-bubble__cursor {
    animation: none;
    opacity: 1;
  }

  .content-fade-enter-active {
    transition: none;
  }
}
</style>
