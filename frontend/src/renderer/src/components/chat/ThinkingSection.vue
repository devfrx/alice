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
    <div class="thinking-section" :class="{ 'thinking-section--streaming': isStreaming && !collapsed }" role="region"
        aria-label="Ragionamento del modello">
        <button class="thinking-section__toggle" :aria-expanded="!collapsed" aria-label="Mostra/nascondi ragionamento"
            @click="collapsed = !collapsed">
            <svg class="thinking-section__icon" width="14" height="14" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path
                    d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z" />
                <line x1="9" y1="21" x2="15" y2="21" />
                <line x1="10" y1="23" x2="14" y2="23" />
            </svg>
            <span class="thinking-section__label">Ragionamento</span>
            <span v-if="collapsed && badgeText" class="thinking-section__badge">{{ badgeText }} caratteri</span>
            <span v-if="isStreaming && !collapsed" class="thinking-section__streaming-text">pensando...</span>
            <svg class="thinking-section__chevron" :class="{ 'thinking-section__chevron--collapsed': collapsed }"
                width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9" />
            </svg>
        </button>
        <div class="thinking-section__body" :class="{ 'thinking-section__body--collapsed': collapsed }">
            <div class="thinking-section__inner">
                <!-- eslint-disable-next-line vue/no-v-html -->
                <div class="thinking-section__content" v-html="thinkingHtml" @click="handleCodeBlockClick" />
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

.thinking-section__streaming-text {
    font-size: var(--text-2xs);
    color: var(--text-muted);
    animation: thinkingPulse 2s ease-in-out infinite;
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

.thinking-section__body>.thinking-section__inner {
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

@keyframes thinkingPulse {

    0%,
    100% {
        opacity: 0.4;
    }

    50% {
        opacity: 1;
    }
}

@media (prefers-reduced-motion: reduce) {

    .thinking-section__chevron,
    .thinking-section__body,
    .thinking-section__streaming-text {
        animation: none;
        transition: none;
    }
}
</style>
