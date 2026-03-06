<script setup lang="ts">
/**
 * ToolCallSection.vue — Collapsible display of tool calls on a message.
 *
 * Follows the same collapsible pattern as ThinkingSection.vue.
 * Shows tool function names and their JSON arguments.
 */
import { computed, ref } from 'vue'

import type { ToolCall } from '../../types/chat'

const props = defineProps<{
    /** The tool_calls array from the assistant message. */
    toolCalls: ToolCall[]
}>()

const collapsed = ref(true)

const badgeText = computed(() => {
    const n = props.toolCalls.length
    return n === 1 ? '1 tool call' : `${n} tool calls`
})

/** Parse arguments JSON safely. */
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
        <button class="tool-section__toggle" :aria-expanded="!collapsed" @click="collapsed = !collapsed">
            <svg class="tool-section__icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91
          6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
            </svg>
            <span class="tool-section__label">Strumenti</span>
            <span v-if="collapsed" class="tool-section__badge">{{ badgeText }}</span>
            <svg class="tool-section__chevron" :class="{ 'tool-section__chevron--collapsed': collapsed }" width="12"
                height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9" />
            </svg>
        </button>

        <div class="tool-section__body" :class="{ 'tool-section__body--collapsed': collapsed }">
            <div class="tool-section__inner">
                <div v-for="tc in toolCalls" :key="tc.id" class="tool-section__item">
                    <span class="tool-section__fn-name">{{ tc.function.name }}</span>
                    <pre class="tool-section__args"><code>{{ formatArgs(tc.function.arguments) }}</code></pre>
                </div>
            </div>
        </div>
        <div class="tool-section__separator" />
    </div>
</template>

<style scoped>
.tool-section {
    margin-bottom: 8px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-left: 3px solid var(--accent-border);
    border-radius: var(--radius-md);
    background: linear-gradient(135deg, rgba(201, 168, 76, 0.03), transparent);
    overflow: hidden;
}

.tool-section__toggle {
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

.tool-section__toggle:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.04);
}

.tool-section__icon {
    flex-shrink: 0;
    opacity: 0.7;
}

.tool-section__label {
    font-style: italic;
    flex: 1;
    text-align: left;
}

.tool-section__badge {
    font-size: 0.68rem;
    color: var(--text-secondary);
    opacity: 0.5;
    background: rgba(255, 255, 255, 0.04);
    padding: 1px 6px;
    border-radius: 8px;
    font-style: normal;
}

.tool-section__chevron {
    flex-shrink: 0;
    transition: transform 0.2s ease;
}

.tool-section__chevron--collapsed {
    transform: rotate(-90deg);
}

.tool-section__body {
    display: grid;
    grid-template-rows: 1fr;
    transition: grid-template-rows 0.35s cubic-bezier(0.4, 0, 0.2, 1),
        padding 0.35s cubic-bezier(0.4, 0, 0.2, 1),
        opacity 0.3s ease;
    padding: 4px 12px 10px;
    opacity: 0.85;
}

.tool-section__body--collapsed {
    grid-template-rows: 0fr;
    padding-top: 0;
    padding-bottom: 0;
    opacity: 0;
}

.tool-section__inner {
    overflow: hidden;
    min-height: 0;
}

.tool-section__item {
    margin-bottom: 8px;
}

.tool-section__item:last-child {
    margin-bottom: 0;
}

.tool-section__fn-name {
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 0.76rem;
    color: var(--accent);
    background: rgba(201, 168, 76, 0.08);
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    margin-bottom: 4px;
}

.tool-section__args {
    margin: 4px 0 0;
    padding: 6px 10px;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    line-height: 1.5;
    color: var(--text-secondary);
    background: rgba(0, 0, 0, 0.2);
    border-radius: var(--radius-sm);
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
}

.tool-section__separator {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(201, 168, 76, 0.15), transparent);
    margin: 0 12px;
}
</style>
