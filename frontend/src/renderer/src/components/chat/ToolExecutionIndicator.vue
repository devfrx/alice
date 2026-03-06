<script setup lang="ts">
/**
 * ToolExecutionIndicator.vue — Live tool execution state during streaming.
 *
 * Shows a compact list of tool executions with status icons
 * (spinner, check, or error) and truncated result snippets.
 */
import { computed } from 'vue'

import type { ToolExecution } from '../../types/chat'

const props = defineProps<{
    /** Active tool executions from the store. */
    executions: ToolExecution[]
}>()

const hasExecutions = computed(() => props.executions.length > 0)

/** Truncate a result string to ~100 characters. */
function truncate(text: string, max = 100): string {
    return text.length > max ? text.slice(0, max) + '…' : text
}
</script>

<template>
    <div v-if="hasExecutions" class="tool-exec">
        <div v-for="exec in executions" :key="exec.executionId" class="tool-exec__item">
            <!-- Status icon -->
            <span v-if="exec.status === 'running'" class="tool-exec__spinner" aria-label="In esecuzione" />
            <svg v-else-if="exec.status === 'done' && exec.success" class="tool-exec__icon tool-exec__icon--ok"
                width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
                stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12" />
            </svg>
            <svg v-else class="tool-exec__icon tool-exec__icon--err" width="14" height="14" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
            </svg>

            <!-- Tool name -->
            <span class="tool-exec__name">{{ exec.toolName }}</span>

            <!-- Result snippet -->
            <span v-if="exec.result" class="tool-exec__result">{{ truncate(exec.result) }}</span>
        </div>
    </div>
</template>

<style scoped>
.tool-exec {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 12px;
    margin-top: 6px;
    background: rgba(255, 255, 255, 0.02);
    border-radius: var(--radius-md);
    border: 1px solid rgba(255, 255, 255, 0.04);
}

.tool-exec__item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.78rem;
    line-height: 1.4;
}

/* Animated spinner */
.tool-exec__spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(201, 168, 76, 0.2);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: toolSpin 0.8s linear infinite;
    flex-shrink: 0;
}

.tool-exec__icon {
    flex-shrink: 0;
}

.tool-exec__icon--ok {
    color: #4ade80;
}

.tool-exec__icon--err {
    color: #f87171;
}

.tool-exec__name {
    font-family: var(--font-mono);
    color: var(--accent);
    font-size: 0.76rem;
    white-space: nowrap;
}

.tool-exec__result {
    color: var(--text-secondary);
    font-size: 0.72rem;
    opacity: 0.7;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 280px;
}

@keyframes toolSpin {
    to {
        transform: rotate(360deg);
    }
}
</style>
