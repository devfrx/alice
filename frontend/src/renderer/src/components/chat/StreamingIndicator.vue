<script setup lang="ts">
/**
 * StreamingIndicator.vue — Shows the in-progress assistant response.
 *
 * Renders partial markdown as it streams in, styled identically to an
 * assistant {@link MessageBubble} but with a glowing caret cursor appended.
 * Includes a collapsible "Ragionamento" section for thinking tokens.
 * The parent controls visibility (`v-if="isStreaming"` outside).
 * The ReasoningThread / tool-execution card is mounted separately in ChatPanel.
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
      <!-- Thinking-only state: shimmer label -->
      <div v-if="thinkingContent && !content" class="streaming-bubble__thinking-state">
        <span class="streaming-bubble__thinking-label streaming-bubble__thinking-label--shimmer"
          >Ragionamento…</span
        >
      </div>

      <!-- Thinking section -->
      <ThinkingSection
        v-if="thinkingContent"
        :thinking-html="thinkingHtml"
        :initial-collapsed="true"
        :auto-expand="true"
        :content-length="thinkingContent.length"
      >
        <span v-if="!content" class="streaming-bubble__cursor" />
      </ThinkingSection>

      <!-- Main content -->
      <Transition name="content-fade">
        <!-- eslint-disable vue/no-v-html -- sanitized markdown render (markdown-it html:false) -->
        <div
          v-if="content"
          class="streaming-bubble__content"
          @click="handleCodeBlockClick"
          v-html="htmlContent"
        />
        <!-- eslint-enable vue/no-v-html -->
      </Transition>
      <span v-if="content || !thinkingContent" class="streaming-bubble__cursor" />
    </div>
  </div>
</template>

<style scoped>
/* StreamingIndicator — Supabase-clean */

.bubble-row {
  display: flex;
  justify-content: flex-start;
  margin-bottom: var(--space-3);
}

.streaming-bubble {
  max-width: 82%;
  padding: var(--space-3) var(--space-4);
  background: transparent;
  border: none;
  color: var(--text-primary);
  line-height: var(--leading-relaxed);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  word-break: break-word;
  position: relative;
}

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
  text-decoration-color: var(--accent-border);
  text-underline-offset: 2px;
  transition: text-decoration-color var(--transition-fast);
}

.streaming-bubble__content :deep(a:hover) {
  text-decoration-color: var(--accent);
}

.streaming-bubble__thinking-state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  padding: var(--space-2) var(--space-3);
}

.streaming-bubble__thinking-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.streaming-bubble__thinking-label--shimmer {
  font-size: var(--text-xs);
  background: linear-gradient(
    90deg,
    var(--text-muted) 28%,
    var(--accent) 50%,
    var(--text-muted) 72%
  );
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: thinkingShimmer 2.3s linear infinite;
}

@keyframes thinkingShimmer {
  0% {
    background-position: 170% 0;
  }
  100% {
    background-position: -70% 0;
  }
}

.streaming-bubble__cursor {
  display: inline-block;
  width: 2px;
  height: 1.05em;
  margin-left: 3px;
  vertical-align: text-bottom;
  border-radius: 1px;
  background: var(--accent);
  box-shadow:
    -9px 0 10px -3px var(--accent-glow),
    0 0 6px var(--accent-glow);
  animation: cursorPulse 1.4s ease-in-out infinite;
}

@keyframes cursorPulse {
  0%,
  100% {
    opacity: 0.95;
  }
  50% {
    opacity: 0.25;
  }
}

.content-fade-enter-active {
  transition: opacity var(--duration-fast) ease;
}

.content-fade-enter-from {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .streaming-bubble__cursor {
    animation: none;
    opacity: 1;
    box-shadow: 0 0 4px var(--accent-glow);
  }

  .content-fade-enter-active {
    transition: none;
  }

  .streaming-bubble__thinking-label--shimmer {
    animation: none;
    color: var(--text-muted);
    -webkit-text-fill-color: var(--text-muted);
  }
}
</style>
