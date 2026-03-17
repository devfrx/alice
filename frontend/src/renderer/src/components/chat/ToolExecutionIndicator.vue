<script setup lang="ts">
/**
 * ToolExecutionIndicator.vue — Live tool execution state during streaming.
 *
 * Shows a compact list of tool executions with status icons
 * (spinner, check, or error) and truncated result snippets.
 */
import { computed, defineAsyncComponent } from 'vue'

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

/** Truncate a result string to ~100 characters. */
function truncate(text: string, max = 100): string {
    return text.length > max ? text.slice(0, max) + '…' : text
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
</script>

<template>
    <div v-if="hasExecutions" class="tool-exec">
        <div v-for="exec in executions" :key="exec.executionId" class="tool-exec__item">
            <!-- Status icon -->
            <OmniaSpinner v-if="exec.status === 'running'" size="xs" aria-label="In esecuzione" />
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

            <!-- Result snippet (CAD model, image, or text) -->
            <img v-if="exec.result && exec.contentType?.startsWith('image/')" class="tool-exec__image"
                :src="`data:${exec.contentType};base64,${exec.result}`" alt="Screenshot" />
            <template v-else-if="exec.contentType === 'application/vnd.omnia.cad-model+json' && exec.result">
                <CADViewer :model-url="parseCadPayload(exec.result)?.export_url ?? ''"
                    :model-name="parseCadPayload(exec.result)?.model_name" />
            </template>
            <template
                v-else-if="exec.contentType === 'application/vnd.omnia.chart+json' && exec.result && parseChartPayload(exec.result)">
                <ChartViewer :payload="chartPayloadOf(exec.result)" />
            </template>
            <span v-else-if="exec.result" class="tool-exec__result">{{ truncate(exec.result) }}</span>
        </div>
    </div>
</template>

<style scoped>
/* ToolExecutionIndicator — Supabase-clean status log */

.tool-exec {
    display: flex;
    flex-direction: column;
    gap: 0;
    padding: var(--space-1) var(--space-3);
    margin-top: var(--space-2);
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    overflow: hidden;
}

.tool-exec__item {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    line-height: var(--leading-tight);
    padding: var(--space-1-5) 0;
    flex-wrap: wrap;
}

/* Viewers (CAD / Chart) take full row width below the status line */
.tool-exec__item :deep(.chart-viewer),
.tool-exec__item :deep(.cad-viewer) {
    flex-basis: 100%;
}

.tool-exec__item:not(:last-child) {
    border-bottom: 1px solid var(--border);
}

.tool-exec__icon {
    flex-shrink: 0;
}

.tool-exec__icon--ok {
    color: var(--success);
}

.tool-exec__icon--err {
    color: var(--danger);
}

.tool-exec__name {
    font-family: var(--font-mono);
    color: var(--text-primary);
    font-size: var(--text-sm);
    white-space: nowrap;
}

.tool-exec__result {
    color: var(--text-secondary);
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 300px;
}

.tool-exec__image {
    max-width: 200px;
    border-radius: var(--radius-xs);
    border: 1px solid var(--border);
    object-fit: contain;
    margin-top: var(--space-1);
}
</style>
