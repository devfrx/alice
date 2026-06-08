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
import AgentActivityCard from './AgentActivityCard.vue'
import AliceSpinner from '../../components/ui/AliceSpinner.vue'

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
        <AliceSpinner size="xs" />
        <span class="streaming-bubble__thinking-label">Ragionamento in corso…</span>
      </div>

      <!-- Thinking section -->
      <ThinkingSection v-if="thinkingContent" :thinking-html="thinkingHtml" :initial-collapsed="true"
        :auto-expand="true" :content-length="thinkingContent.length">
        <span v-if="!content" class="streaming-bubble__cursor" />
      </ThinkingSection>

      <!-- Tool execution indicator -->
      <ToolExecutionIndicator :executions="chatStore.activeToolExecutions" />

      <!-- Per-turn run budget / status (canonical turn-event stream; self-guards) -->
      <AgentActivityCard />

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

.streaming-bubble__cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--accent);
  animation: cursorBlink 1s steps(2) infinite;
}

.content-fade-enter-active {
  transition: opacity 120ms ease;
}

.content-fade-enter-from {
  opacity: 0;
}

@keyframes cursorBlink {

  0%,
  49.9% {
    opacity: 1;
  }

  50%,
  100% {
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .streaming-bubble__cursor {
    animation: none;
    opacity: 1;
  }

  .content-fade-enter-active {
    transition: none;
  }
}
</style>
