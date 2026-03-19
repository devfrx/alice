<script setup lang="ts">
/**
 * ToolCallSection.vue — Timeline-style display of tool calls on a message.
 *
 * Shows an always-visible list of tool names with a vertical timeline connector.
 * Each tool call can be individually expanded to reveal its arguments.
 * Header toggle expands/collapses all at once.
 */
import { computed, reactive } from 'vue'

import type { ToolCall } from '../../types/chat'

const props = defineProps<{
    /** The tool_calls array from the assistant message. */
    toolCalls: ToolCall[]
}>()

/** Set of expanded tool call IDs (per-tool toggle). */
const expandedCalls = reactive(new Set<string>())

const badgeText = computed(() => {
    const n = props.toolCalls.length
    return n === 1 ? '1 strumento' : `${n} strumenti`
})

const allExpanded = computed(
    () => props.toolCalls.length > 0 && props.toolCalls.every((tc) => expandedCalls.has(tc.id ?? ''))
)

function toggleAll(): void {
    if (allExpanded.value) {
        expandedCalls.clear()
    } else {
        for (const tc of props.toolCalls) {
            if (tc.id) expandedCalls.add(tc.id)
        }
    }
}

function toggleCall(id: string | undefined): void {
    if (!id) return
    if (expandedCalls.has(id)) {
        expandedCalls.delete(id)
    } else {
        expandedCalls.add(id)
    }
}

/** Extract a one-line summary from args JSON (first string value). */
function argsSummary(args: string): string {
    try {
        const obj = JSON.parse(args)
        const entries = Object.entries(obj)
        if (entries.length === 0) return ''
        const [key, val] = entries[0]
        const valStr = typeof val === 'string' ? val : JSON.stringify(val)
        const truncated = valStr.length > 60 ? valStr.slice(0, 60) + '…' : valStr
        return `${key}: ${truncated}`
    } catch {
        return ''
    }
}

/** Parse arguments JSON safely for full display. */
function formatArgs(args: string): string {
    try {
        return JSON.stringify(JSON.parse(args), null, 2)
    } catch {
        return args
    }
}
</script>

<template>
    <div class="tool-section" role="region" aria-label="Tool calls">
        <!-- Header -->
        <button class="tool-section__header" :aria-expanded="allExpanded" @click="toggleAll">
            <svg class="tool-section__icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path
                    d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
            </svg>
            <span class="tool-section__title">Strumenti usati</span>
            <span class="tool-section__badge">{{ badgeText }}</span>
            <svg class="tool-section__chevron" :class="{ 'tool-section__chevron--open': allExpanded }" width="12"
                height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <polyline points="6 9 12 15 18 9" />
            </svg>
        </button>

        <!-- Timeline list (always visible) -->
        <div class="tool-section__timeline">
            <div v-for="(tc, index) in toolCalls" :key="tc.id ?? index" class="tool-section__step"
                :class="{ 'tool-section__step--last': index === toolCalls.length - 1 }">
                <div class="tool-section__rail">
                    <span class="tool-section__dot" />
                </div>
                <div class="tool-section__step-body">
                    <button class="tool-section__step-header" @click="toggleCall(tc.id)">
                        <span class="tool-section__fn">{{ tc.function.name }}</span>
                        <span v-if="!expandedCalls.has(tc.id ?? '')" class="tool-section__hint">
                            {{ argsSummary(tc.function.arguments) }}
                        </span>
                        <svg class="tool-section__step-chevron"
                            :class="{ 'tool-section__step-chevron--open': expandedCalls.has(tc.id ?? '') }" width="10"
                            height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                            <polyline points="6 9 12 15 18 9" />
                        </svg>
                    </button>
                    <div class="tool-section__args-wrapper"
                        :class="{ 'tool-section__args-wrapper--collapsed': !expandedCalls.has(tc.id ?? '') }">
                        <div class="tool-section__args-inner">
                            <pre class="tool-section__args"><code>{{ formatArgs(tc.function.arguments) }}</code></pre>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="tool-section__separator" />
    </div>
</template>

<style scoped>
.tool-section {
    position: relative;
    margin-bottom: var(--space-2);
}

/* Header */
.tool-section__header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-1-5) 0;
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: var(--text-xs);
    cursor: pointer;
    text-align: left;
    transition: color var(--transition-fast);
}

.tool-section__header:hover {
    color: var(--text-primary);
}

.tool-section__icon {
    flex-shrink: 0;
    width: 12px;
    height: 12px;
    color: var(--text-secondary);
}

.tool-section__title {
    flex: 1;
    text-align: left;
    font-size: var(--text-xs);
    color: inherit;
}

.tool-section__badge {
    font-size: var(--text-2xs);
    color: var(--text-muted);
    background: var(--surface-3);
    padding: var(--space-0-5) var(--space-2);
    border-radius: var(--radius-pill);
    line-height: var(--leading-snug);
}

.tool-section__chevron {
    flex-shrink: 0;
    width: 10px;
    height: 10px;
    color: var(--text-muted);
    transition: transform var(--transition-fast);
}

.tool-section__chevron--open {
    transform: rotate(180deg);
}

/* Timeline */
.tool-section__timeline {
    padding: var(--space-1) 0 var(--space-1) var(--space-1);
}

.tool-section__step {
    display: flex;
    gap: var(--space-2);
    position: relative;
}

/* Rail — vertical connector */
.tool-section__rail {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 12px;
    flex-shrink: 0;
    position: relative;
}

/* Vertical line between dots */
.tool-section__step:not(.tool-section__step--last) .tool-section__rail::after {
    content: '';
    position: absolute;
    top: 14px;
    left: 50%;
    transform: translateX(-50%);
    width: 1px;
    bottom: 0;
    background: var(--border);
}

.tool-section__dot {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-full);
    background: var(--accent);
    opacity: 0.6;
    margin-top: 6px;
    flex-shrink: 0;
    z-index: 1;
}

/* Step body */
.tool-section__step-body {
    flex: 1;
    min-width: 0;
    padding-bottom: var(--space-1);
}

.tool-section__step-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-0-5) 0;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    color: var(--text-secondary);
    transition: color var(--transition-fast);
}

.tool-section__step-header:hover {
    color: var(--text-primary);
}

.tool-section__fn {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--accent);
    font-weight: var(--weight-medium);
    white-space: nowrap;
}

.tool-section__hint {
    flex: 1;
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}

.tool-section__step-chevron {
    flex-shrink: 0;
    width: 8px;
    height: 8px;
    color: var(--text-muted);
    transition: transform var(--transition-fast);
}

.tool-section__step-chevron--open {
    transform: rotate(180deg);
}

/* Expandable args */
.tool-section__args-wrapper {
    display: grid;
    grid-template-rows: 1fr;
    opacity: 1;
    transition:
        grid-template-rows var(--duration-normal) ease,
        opacity var(--duration-normal) ease;
}

.tool-section__args-wrapper--collapsed {
    grid-template-rows: 0fr;
    opacity: 0;
    pointer-events: none;
}

.tool-section__args-inner {
    overflow: hidden;
    min-height: 0;
}

.tool-section__args {
    margin: var(--space-1) 0 0;
    padding: var(--space-2) var(--space-3);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    line-height: 1.6;
    color: var(--text-secondary);
    background: var(--surface-1);
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    user-select: text;
    cursor: text;
    max-height: 200px;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
}

.tool-section__args::-webkit-scrollbar {
    width: 3px;
}

.tool-section__args::-webkit-scrollbar-track {
    background: transparent;
}

.tool-section__args::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: var(--radius-xs);
}

.tool-section__args code {
    font-family: inherit;
    font-size: inherit;
    color: inherit;
    background: none;
}

/* Separator */
.tool-section__separator {
    height: 1px;
    margin: var(--space-2) 0;
    background: var(--border);
}

@media (prefers-reduced-motion: reduce) {

    .tool-section__args-wrapper,
    .tool-section__chevron,
    .tool-section__step-chevron,
    .tool-section__header,
    .tool-section__step-header {
        transition: none;
    }
}
</style>
