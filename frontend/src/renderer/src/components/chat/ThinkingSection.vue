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
.thinking-section {
    margin-bottom: 8px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-left: 3px solid var(--accent-border);
    border-radius: var(--radius-md);
    background: linear-gradient(135deg, rgba(201, 168, 76, 0.03), transparent);
    overflow: hidden;
    transition: border-color 0.3s ease;
}

/* Pulsing left border glow while streaming */
.thinking-section--streaming {
    animation: thinkingBorderPulse 2s ease-in-out infinite;
}

.thinking-section__toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 8px 12px;
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 0.78rem;
    cursor: pointer;
    border-radius: var(--radius-md);
    transition: color 0.2s ease, background 0.2s ease;
}

.thinking-section__toggle:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.04);
}

.thinking-section__toggle:active {
    background: rgba(255, 255, 255, 0.06);
}

.thinking-section__icon {
    flex-shrink: 0;
    opacity: 0.7;
}

.thinking-section__label {
    font-style: italic;
    flex: 1;
    text-align: left;
}

.thinking-section__badge {
    font-size: 0.68rem;
    color: var(--text-secondary);
    opacity: 0.5;
    background: rgba(255, 255, 255, 0.04);
    padding: 1px 6px;
    border-radius: 8px;
    font-style: normal;
}

.thinking-section__streaming-text {
    font-size: 0.72rem;
    font-style: italic;
    color: var(--accent);
    opacity: 0.8;
    animation: thinkingTextPulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

.thinking-section__chevron {
    flex-shrink: 0;
    transition: transform 0.2s ease;
}

.thinking-section__chevron--collapsed {
    transform: rotate(-90deg);
}

.thinking-section__body {
    display: grid;
    grid-template-rows: 1fr;
    transition: grid-template-rows 0.35s cubic-bezier(0.4, 0, 0.2, 1),
                padding 0.35s cubic-bezier(0.4, 0, 0.2, 1),
                opacity 0.3s ease;
    padding: 6px 12px 10px;
    font-style: italic;
    color: var(--text-secondary);
    font-size: 0.82rem;
    line-height: 1.55;
    opacity: 0.75;
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
    position: relative;
}

.thinking-section__separator {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(201, 168, 76, 0.15), transparent);
    margin: 0 12px;
}

.thinking-section__content :deep(p) {
    margin: 0 0 0.4em;
}

.thinking-section__content :deep(p:last-child) {
    margin-bottom: 0;
}

@keyframes thinkingBorderPulse {
    0%, 100% {
        border-left-color: var(--accent-border);
    }
    50% {
        border-left-color: var(--accent);
    }
}

@keyframes thinkingTextPulse {
    0%, 100% {
        opacity: 0.8;
    }
    40% {
        opacity: 0.35;
    }
    60% {
        opacity: 0.35;
    }
}
</style>
