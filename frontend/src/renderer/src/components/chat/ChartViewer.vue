<script setup lang="ts">
/**
 * ChartViewer.vue — Visualizza un grafico Apache ECharts nella chat.
 *
 * Carica la ChartSpec completa dall'endpoint REST GET /api/charts/{chart_id},
 * monta un'istanza echarts.init() sul div container e gestisce il resize.
 */
import { ref, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import type { ECharts } from 'echarts'
import { resolveBackendUrl } from '../../services/api'
import type { ChartPayload } from '../../types/chat'

const props = defineProps<{ payload: ChartPayload }>()

const containerRef = ref<HTMLDivElement | null>(null)
let instance: ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let unmounted = false

/** Data fetched, ready to init echarts on a visible container. */
const ready = ref(false)
const loading = ref(true)
const error = ref<string | null>(null)
let fetchedOption: Record<string, unknown> | null = null

/**
 * OMNIA chart color palette — vibrant, accessible on dark backgrounds.
 * Used when the LLM doesn't specify colors or when we override them.
 */
const OMNIA_PALETTE = [
    '#6ee7b7', // emerald
    '#93c5fd', // sky blue
    '#fca5a5', // coral
    '#fcd34d', // amber
    '#c4b5fd', // violet
    '#f9a8d4', // pink
    '#67e8f9', // cyan
    '#fdba74', // orange
    '#a5f3fc', // teal
    '#d9f99d', // lime
]

/**
 * Sanitize and restyle the LLM-generated ECharts option:
 * - Remove internal title (the ChartViewer header already shows it)
 * - Remove visualMap (almost never looks good in chat context)
 * - Remove dataZoom with restrictive start/end that clips data
 * - Force containLabel so axis labels never overflow
 * - Apply OMNIA color palette for consistent look
 * - Fix markPoint/markLine entries with malformed coord arrays
 * - Clean up tooltip, legend, and axis styling for dark theme
 */
function sanitizeOption(opt: Record<string, unknown>): Record<string, unknown> {
    const hadTitle = !!opt.title
    delete opt.title

    // Remove visualMap — it adds a distracting color bar and
    // overrides the series colors with gradients.
    delete opt.visualMap

    // Reset dataZoom start/end to show all data by default, but keep
    // the zoom functionality so the user can still pan/scroll.
    if (Array.isArray(opt.dataZoom)) {
        for (const dz of opt.dataZoom as Record<string, unknown>[]) {
            dz.start = 0
            dz.end = 100
        }
    }

    // Remove toolbox — takes space and is not useful in chat context.
    delete opt.toolbox

    // Grid: generous padding, always containLabel.
    const existingGrid = (opt.grid ?? {}) as Record<string, unknown>
    opt.grid = {
        top: hadTitle ? 24 : 14,
        right: 20,
        bottom: 14,
        left: 14,
        ...existingGrid,
        containLabel: true,
    }

    // Apply OMNIA palette.
    opt.color = OMNIA_PALETTE

    // Style legend for dark theme.
    if (opt.legend && typeof opt.legend === 'object') {
        const legend = opt.legend as Record<string, unknown>
        legend.textStyle = { color: '#d1d5db' }
        // Move to bottom to avoid overlapping chart area.
        if (!legend.bottom && !legend.top) {
            legend.bottom = 0
        }
    }

    // Style tooltip.
    opt.tooltip = {
        ...(typeof opt.tooltip === 'object' && opt.tooltip ? opt.tooltip : {}),
        backgroundColor: 'rgba(30, 30, 40, 0.92)',
        borderColor: 'rgba(255, 255, 255, 0.08)',
        textStyle: { color: '#e5e7eb', fontSize: 13 },
    } as Record<string, unknown>

    // Style axes for dark theme.
    for (const axisKey of ['xAxis', 'yAxis']) {
        const axis = opt[axisKey]
        if (axis && typeof axis === 'object' && !Array.isArray(axis)) {
            const ax = axis as Record<string, unknown>
            ax.axisLine = { lineStyle: { color: 'rgba(255,255,255,0.12)' } }
            ax.axisLabel = {
                ...(typeof ax.axisLabel === 'object' && ax.axisLabel ? ax.axisLabel : {}),
                color: '#9ca3af',
            }
            ax.splitLine = { lineStyle: { color: 'rgba(255,255,255,0.06)' } }
        }
    }

    // Sanitize series-level properties that frequently crash ECharts.
    const series = opt.series
    if (Array.isArray(series)) {
        for (const s of series) {
            if (s && typeof s === 'object') {
                const ser = s as Record<string, unknown>
                sanitizeMarkData(ser, 'markPoint')
                sanitizeMarkData(ser, 'markLine')
                // Remove per-series itemStyle color overrides so the
                // palette is used consistently.
                if (ser.itemStyle && typeof ser.itemStyle === 'object') {
                    delete (ser.itemStyle as Record<string, unknown>).color
                }
            }
        }
    }

    return opt
}

/**
 * Check whether a single mark entry has a valid coord (2-element array).
 * Returns false for entries with missing or incomplete coord.
 */
function isValidMarkEntry(item: unknown): boolean {
    if (!item || typeof item !== 'object') return false
    const entry = item as Record<string, unknown>
    if ('coord' in entry) {
        const coord = entry.coord
        if (!Array.isArray(coord) || coord.length < 2) return false
    }
    return true
}

/**
 * Wait until an element has non-zero clientWidth and clientHeight.
 * Uses ResizeObserver to avoid polling. Resolves immediately if the
 * element already has dimensions. Times out after 2 seconds.
 */
function waitForDimensions(el: HTMLElement): Promise<void> {
    if (el.clientWidth > 0 && el.clientHeight > 0) return Promise.resolve()
    return new Promise<void>((resolve) => {
        const timeout = setTimeout(() => { ro.disconnect(); resolve() }, 2000)
        const ro = new ResizeObserver(() => {
            if (el.clientWidth > 0 && el.clientHeight > 0) {
                ro.disconnect()
                clearTimeout(timeout)
                resolve()
            }
        })
        ro.observe(el)
    })
}

/**
 * Remove markPoint/markLine data entries with invalid coord arrays.
 * ECharts requires coord to be a 2-element [x, y] array; LLMs often
 * produce single-element arrays like ["2025"] which crash the renderer.
 *
 * markLine data items can be either flat objects or 2-element arrays
 * representing line endpoints: [[{coord: [x1,y1]}, {coord: [x2,y2]}]].
 */
function sanitizeMarkData(series: Record<string, unknown>, key: string): void {
    const mark = series[key]
    if (!mark || typeof mark !== 'object') return
    const markObj = mark as Record<string, unknown>
    const data = markObj.data
    if (!Array.isArray(data)) return

    markObj.data = data.filter((item) => {
        if (item == null) return false
        // Nested array of endpoint pairs: [[pointA, pointB]]
        if (Array.isArray(item)) {
            return item.every(isValidMarkEntry)
        }
        // Flat object entry
        return isValidMarkEntry(item)
    })
}

async function loadAndRender(): Promise<void> {
    try {
        const response = await fetch(resolveBackendUrl(props.payload.chart_url))
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const spec = await response.json()
        fetchedOption = sanitizeOption(spec.echarts_option)

        // Make the canvas div visible BEFORE echarts.init so it has real dimensions.
        ready.value = true
        loading.value = false
        await nextTick()

        if (unmounted || !containerRef.value) return

        // Wait until the container has real dimensions (> 0).
        // This handles the side-panel slide transition where the panel
        // starts at width: 0 and animates to 400px.
        await waitForDimensions(containerRef.value)
        if (unmounted) return

        instance = echarts.init(containerRef.value, 'dark')
        try {
            instance.setOption(fetchedOption!)
        } catch (renderErr) {
            console.warn('[ChartViewer] ECharts setOption error, retrying without marks:', renderErr)
            // Strip all markPoint/markLine/visualMap and retry
            const fallback = { ...fetchedOption! }
            const series = fallback.series
            if (Array.isArray(series)) {
                for (const s of series) {
                    if (s && typeof s === 'object') {
                        delete (s as Record<string, unknown>).markPoint
                        delete (s as Record<string, unknown>).markLine
                    }
                }
            }
            delete fallback.visualMap
            instance.setOption(fallback)
        }

        resizeObserver = new ResizeObserver(() => instance?.resize())
        resizeObserver.observe(containerRef.value)
    } catch (err) {
        error.value = `Impossibile caricare il grafico: ${(err as Error).message}`
        loading.value = false
    }
}

onMounted(loadAndRender)

onUnmounted(() => {
    unmounted = true
    resizeObserver?.disconnect()
    instance?.dispose()
    instance = null
})
</script>

<template>
    <div class="chart-viewer">
        <div class="chart-viewer__header">
            <span class="chart-viewer__title">{{ payload.title }}</span>
            <span class="chart-viewer__type">{{ payload.chart_type }}</span>
        </div>
        <div v-if="loading" class="chart-viewer__loading">Caricamento grafico…</div>
        <div v-if="error" class="chart-viewer__error">{{ error }}</div>
        <div v-if="ready && !error" ref="containerRef" class="chart-viewer__canvas" />
    </div>
</template>

<style scoped>
.chart-viewer {
    border-radius: 8px;
    overflow: hidden;
    background: var(--surface-2);
    margin: 8px 0;
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
}

.chart-viewer__header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: var(--surface-3);
    border-bottom: 1px solid var(--border);
}

.chart-viewer__title {
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary);
    flex: 1;
}

.chart-viewer__type {
    font-size: 0.75rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.chart-viewer__canvas {
    width: 100%;
    height: 380px;
    min-height: 280px;
    flex: 1;
}

.chart-viewer__loading,
.chart-viewer__error {
    padding: 24px;
    text-align: center;
    color: var(--text-secondary);
    font-size: 0.875rem;
}

.chart-viewer__error {
    color: var(--danger);
}
</style>
