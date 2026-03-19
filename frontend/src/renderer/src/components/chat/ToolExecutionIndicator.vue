<script setup lang="ts">
/**
 * ToolExecutionIndicator.vue — Live tool execution timeline during streaming.
 *
 * Shows a vertical timeline of tool executions with status-aware dots
 * (pulsing for running, check for done, cross for error) and result previews.
 * Visual language matches ToolCallSection's timeline design.
 */
import { computed, reactive, defineAsyncComponent } from 'vue'

import type { ToolExecution, ChartPayload } from '../../types/chat'
import OmniaSpinner from '../../components/ui/OmniaSpinner.vue'

const CADViewer = defineAsyncComponent(
    () => import('./CADViewer.vue')
)
const ChartViewer = defineAsyncComponent(
    () => import('./ChartViewer.vue')
)

const props = defineProps<{
    /** Active tool executions from the store. */
    executions: ToolExecution[]
}>()

const hasExecutions = computed(() => props.executions.length > 0)

/** Set of expanded result IDs. */
const expandedResults = reactive(new Set<string>())

function toggleResult(id: string): void {
    if (expandedResults.has(id)) {
        expandedResults.delete(id)
    } else {
        expandedResults.add(id)
    }
}

/** Truncate a result string to ~80 characters for preview. */
function truncate(text: string, max = 80): string {
    const line = text.split('\n')[0] ?? text
    return line.length > max ? line.slice(0, max) + '…' : line
}

/** Try to parse a CAD model JSON payload from a tool result string. */
function parseCadPayload(result: string): { export_url: string; model_name: string } | null {
    try {
        const p = JSON.parse(result)
        if (typeof p.model_name === 'string' && typeof p.export_url === 'string') return p
        return null
    } catch { return null }
}

/** Try to parse a Chart JSON payload from a tool result string. */
function parseChartPayload(result: string): ChartPayload | null {
    try {
        const p = JSON.parse(result)
        if (typeof p.chart_id === 'string' && typeof p.chart_url === 'string' && typeof p.chart_type === 'string') return p as ChartPayload
        return null
    } catch { return null }
}

/** Non-null variant used inside guarded template blocks. */
function chartPayloadOf(result: string): ChartPayload {
    return parseChartPayload(result) as ChartPayload
}

/** Check if result is a plain text result (not special payload). */
function isPlainResult(exec: ToolExecution): boolean {
    if (!exec.result) return false
    if (exec.contentType?.startsWith('image/')) return false
    if (exec.contentType === 'application/vnd.omnia.cad-model+json') return false
    if (exec.contentType === 'application/vnd.omnia.chart+json' && parseChartPayload(exec.result)) return false
    return true
}
</script>

<template>
    <div v-if="hasExecutions" class="tool-exec" role="log" aria-label="Esecuzione strumenti">
        <div v-for="(exec, index) in executions" :key="exec.executionId" class="tool-exec__step"
            :class="{ 'tool-exec__step--last': index === executions.length - 1 }">
            <div class="tool-exec__rail">
                <!-- Status dot -->
                <span v-if="exec.status === 'running'" class="tool-exec__dot tool-exec__dot--running" />
                <span v-else-if="exec.status === 'done' && exec.success" class="tool-exec__dot tool-exec__dot--ok" />
                <span v-else class="tool-exec__dot tool-exec__dot--err" />
            </div>

            <div class="tool-exec__body">
                <!-- Tool name + status row -->
                <div class="tool-exec__header">
                    <OmniaSpinner v-if="exec.status === 'running'" size="xs" aria-label="In esecuzione" />
                    <svg v-else-if="exec.status === 'done' && exec.success" class="tool-exec__status-icon" width="12"
                        height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
                        stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                    </svg>
                    <svg v-else class="tool-exec__status-icon tool-exec__status-icon--err" width="12" height="12"
                        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
                        stroke-linejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                    <span class="tool-exec__name">{{ exec.toolName }}</span>
                </div>

                <!-- Result area -->
                <template v-if="exec.result">
                    <!-- Image result -->
                    <img v-if="exec.contentType?.startsWith('image/')" class="tool-exec__image"
                        :src="`data:${exec.contentType};base64,${exec.result}`" alt="Screenshot" />
                    <!-- CAD model -->
                    <template v-else-if="exec.contentType === 'application/vnd.omnia.cad-model+json'">
                        <CADViewer :model-url="parseCadPayload(exec.result)?.export_url ?? ''"
                            :model-name="parseCadPayload(exec.result)?.model_name" />
                    </template>
                    <!-- Chart -->
                    <template
                        v-else-if="exec.contentType === 'application/vnd.omnia.chart+json' && parseChartPayload(exec.result)">
                        <ChartViewer :payload="chartPayloadOf(exec.result)" />
                    </template>
                    <!-- Plain text result (collapsible) -->
                    <template v-else-if="isPlainResult(exec)">
                        <button class="tool-exec__result-toggle" @click="toggleResult(exec.executionId)">
                            <span class="tool-exec__result-preview">{{ truncate(exec.result) }}</span>
                            <svg class="tool-exec__result-chevron"
                                :class="{ 'tool-exec__result-chevron--open': expandedResults.has(exec.executionId) }"
                                width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="6 9 12 15 18 9" />
                            </svg>
                        </button>
                        <div class="tool-exec__result-body"
                            :class="{ 'tool-exec__result-body--collapsed': !expandedResults.has(exec.executionId) }">
                            <div class="tool-exec__result-inner">
                                <pre class="tool-exec__result-full">{{ exec.result }}</pre>
                            </div>
                        </div>
                    </template>
                </template>
            </div>
        </div>
    </div>
</template>

<style scoped>
.tool-exec {
    padding: var(--space-2) 0 var(--space-1) var(--space-1);
    margin-top: var(--space-2);
}

.tool-exec__step {
    display: flex;
    gap: var(--space-2);
    position: relative;
}

/* Rail — vertical connector */
.tool-exec__rail {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 12px;
    flex-shrink: 0;
    position: relative;
}

.tool-exec__step:not(.tool-exec__step--last) .tool-exec__rail::after {
    content: '';
    position: absolute;
    top: 14px;
    left: 50%;
    transform: translateX(-50%);
    width: 1px;
    bottom: 0;
    background: var(--border);
}

/* Status dots */
.tool-exec__dot {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-full);
    margin-top: 6px;
    flex-shrink: 0;
    z-index: 1;
}

.tool-exec__dot--running {
    background: var(--accent);
    animation: dotPulse 1.4s ease-in-out infinite;
}

.tool-exec__dot--ok {
    background: var(--success);
}

.tool-exec__dot--err {
    background: var(--danger);
}

@keyframes dotPulse {

    0%,
    100% {
        opacity: 0.4;
    }

    50% {
        opacity: 1;
    }
}

/* Body */
.tool-exec__body {
    flex: 1;
    min-width: 0;
    padding-bottom: var(--space-2);
}

.tool-exec__header {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
}

.tool-exec__status-icon {
    flex-shrink: 0;
    color: var(--success);
}

.tool-exec__status-icon--err {
    color: var(--danger);
}

.tool-exec__name {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--accent);
    font-weight: var(--weight-medium);
    white-space: nowrap;
}

/* Result toggle */
.tool-exec__result-toggle {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
    width: 100%;
    margin-top: var(--space-1);
    padding: 0;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    color: var(--text-muted);
    transition: color var(--transition-fast);
}

.tool-exec__result-toggle:hover {
    color: var(--text-secondary);
}

.tool-exec__result-preview {
    flex: 1;
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}

.tool-exec__result-chevron {
    flex-shrink: 0;
    color: var(--text-muted);
    transition: transform var(--transition-fast);
}

.tool-exec__result-chevron--open {
    transform: rotate(180deg);
}

/* Expandable result body */
.tool-exec__result-body {
    display: grid;
    grid-template-rows: 1fr;
    opacity: 1;
    transition:
        grid-template-rows var(--duration-normal) ease,
        opacity var(--duration-normal) ease;
}

.tool-exec__result-body--collapsed {
    grid-template-rows: 0fr;
    opacity: 0;
    pointer-events: none;
}

.tool-exec__result-inner {
    overflow: hidden;
    min-height: 0;
}

.tool-exec__result-full {
    margin: var(--space-1) 0 0;
    padding: var(--space-2) var(--space-3);
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    line-height: 1.5;
    color: var(--text-secondary);
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 200px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
}

.tool-exec__result-full::-webkit-scrollbar {
    width: 3px;
}

.tool-exec__result-full::-webkit-scrollbar-track {
    background: transparent;
}

.tool-exec__result-full::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: var(--radius-xs);
}

/* Special result types */
.tool-exec__image {
    max-width: 200px;
    border-radius: var(--radius-xs);
    border: 1px solid var(--border);
    object-fit: contain;
    margin-top: var(--space-1);
}

/* Viewers take full width */
.tool-exec__body :deep(.chart-viewer),
.tool-exec__body :deep(.cad-viewer) {
    margin-top: var(--space-1);
}

@media (prefers-reduced-motion: reduce) {

    .tool-exec__result-body,
    .tool-exec__result-chevron,
    .tool-exec__result-toggle,
    .tool-exec__dot--running {
        transition: none;
        animation: none;
    }
}
</style>
