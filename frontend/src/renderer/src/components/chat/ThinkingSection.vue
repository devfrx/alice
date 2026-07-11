<script setup lang="ts">
/**
 * ThinkingSection.vue — Collapsible "Ragionamento" section.
 *
 * Reusable component that renders a collapsible thinking/reasoning
 * section with rendered markdown content. Used by both MessageBubble
 * and StreamingIndicator.
 */
import { ref, watch, computed } from 'vue'

import { useCodeBlocks } from '../../composables/useCodeBlocks'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{
  /** Pre-rendered HTML of thinking content. */
  thinkingHtml: string
  /** Whether the section starts collapsed. */
  initialCollapsed?: boolean
  /** Whether to auto-expand when content grows (for streaming). */
  autoExpand?: boolean
  /** Raw thinking content length, used for auto-expand detection. */
  contentLength?: number
}>()

const collapsed = ref(props.initialCollapsed ?? true)

/** Whether content is actively streaming (growing). */
const isStreaming = computed(() => props.autoExpand === true)

/** Formatted content length for badge display. */
const badgeText = computed(() => {
  const len = props.contentLength ?? 0
  if (len === 0) return ''
  return len > 1000 ? `~${Math.round(len / 100) / 10}k` : String(len)
})

const { handleCodeBlockClick } = useCodeBlocks()

// Auto-expand while thinking tokens are arriving
if (props.autoExpand) {
  watch(
    () => props.contentLength,
    (val, old) => {
      if ((val ?? 0) > (old ?? 0)) {
        collapsed.value = false
      }
    }
  )
}
</script>

<template>
  <div
    class="thinking-section"
    :class="{ 'thinking-section--streaming': isStreaming && !collapsed }"
    role="region"
    aria-label="Ragionamento del modello"
  >
    <button
      class="thinking-section__toggle"
      :aria-expanded="!collapsed"
      aria-label="Mostra/nascondi ragionamento"
      @click="collapsed = !collapsed"
    >
      <AppIcon name="lightbulb" :size="14" class="thinking-section__icon" />
      <span
        class="thinking-section__label"
        :class="{ 'thinking-section__label--shimmer': isStreaming }"
        >Ragionamento</span
      >
      <span v-if="collapsed && badgeText" class="thinking-section__badge"
        >{{ badgeText }} caratteri</span
      >
      <AppIcon
        name="chevron-down"
        :size="12"
        class="thinking-section__chevron"
        :class="{ 'thinking-section__chevron--collapsed': collapsed }"
      />
    </button>
    <div class="thinking-section__body" :class="{ 'thinking-section__body--collapsed': collapsed }">
      <span
        v-if="isStreaming && !collapsed"
        class="thinking-section__railpulse"
        aria-hidden="true"
      />
      <div class="thinking-section__inner">
        <!-- eslint-disable vue/no-v-html -- prop is rendered by the sanitized markdown pipeline (markdown-it html:false) -->
        <div
          class="thinking-section__content"
          @click="handleCodeBlockClick"
          v-html="thinkingHtml"
        />
        <!-- eslint-enable vue/no-v-html -->
        <slot />
      </div>
    </div>
    <div class="thinking-section__separator" />
  </div>
</template>

<style scoped>
/* ThinkingSection — Supabase-clean collapsible */

.thinking-section {
  position: relative;
  margin-bottom: var(--space-2);
  background: transparent;
  overflow: hidden;
}

.thinking-section__toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-1-5) var(--space-2);
  background: none;
  border: none;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--text-xs);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: color var(--transition-fast);
}

.thinking-section__toggle:hover {
  color: var(--text-primary);
}

.thinking-section__icon {
  flex-shrink: 0;
  width: 12px;
  height: 12px;
  color: var(--accent);
}

.thinking-section__label {
  flex: 1;
  text-align: left;
  font-size: var(--text-xs);
  color: inherit;
}

.thinking-section__badge {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  background: var(--surface-3);
  padding: var(--space-0-5) var(--space-2);
  border-radius: var(--radius-pill);
  line-height: var(--leading-snug);
  white-space: nowrap;
}

.thinking-section__chevron {
  flex-shrink: 0;
  width: 10px;
  height: 10px;
  color: var(--text-muted);
  transition: transform var(--transition-fast);
}

.thinking-section__chevron--collapsed {
  transform: rotate(-90deg);
}

.thinking-section__body {
  position: relative;
  display: grid;
  grid-template-rows: 1fr;
  transition:
    grid-template-rows var(--duration-moderate) ease,
    opacity var(--duration-normal) ease;
  padding: 0 var(--space-2) var(--space-2) var(--space-3);
  border-left: 2px solid var(--border);
  margin-left: var(--space-2);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  line-height: var(--leading-snug);
  opacity: 1;
}

.thinking-section__body--collapsed {
  grid-template-rows: 0fr;
  padding-top: 0;
  padding-bottom: 0;
  opacity: 0;
}

.thinking-section__body > .thinking-section__inner {
  overflow: hidden;
  min-height: 0;
}

.thinking-section__separator {
  height: 1px;
  background: var(--border);
  margin: var(--space-2) 0;
}

.thinking-section__content {
  user-select: text;
  cursor: text;
}

.thinking-section__content :deep(p) {
  margin: 0 0 0.4em;
}

.thinking-section__content :deep(p:last-child) {
  margin-bottom: 0;
}

.thinking-section__label--shimmer {
  background: linear-gradient(
    90deg,
    var(--text-secondary) 28%,
    var(--accent) 50%,
    var(--text-secondary) 72%
  );
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: tsShimmer 2.3s linear infinite;
}

@keyframes tsShimmer {
  0% {
    background-position: 170% 0;
  }
  100% {
    background-position: -70% 0;
  }
}

/* glow that travels down the body's left rail */
.thinking-section__railpulse {
  position: absolute;
  left: -2px;
  top: 0;
  width: 2px;
  height: 45%;
  border-radius: 2px;
  background: linear-gradient(to bottom, transparent, var(--accent), transparent);
  box-shadow: 0 0 8px var(--accent-glow);
  animation: tsTravel 1.9s ease-in-out infinite;
  pointer-events: none;
}

@keyframes tsTravel {
  0% {
    top: -45%;
  }
  100% {
    top: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .thinking-section__chevron,
  .thinking-section__body {
    animation: none;
    transition: none;
  }

  .thinking-section__label--shimmer {
    animation: none;
    color: var(--text-secondary);
    -webkit-text-fill-color: var(--text-secondary);
  }

  .thinking-section__railpulse {
    display: none;
  }
}
</style>
