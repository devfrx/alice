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
 * OMNIA chart color palette — warm, muted tones that harmonise with the
 * dark cream-accented interface. Derived from the CSS design tokens:
 * accent #E8DCC8 · success #5C9A6E · warning #D4A72C · danger #B85C5C.
 */
const OMNIA_PALETTE = [
    '#E8DCC8', // cream — primary accent
    '#7BAE8A', // sage green — success-adjacent
    '#D4A72C', // warm amber — warning
    '#8AABC8', // dusty steel blue
    '#C08080', // muted coral — danger-adjacent
    '#B09AC8', // dusty lavender
    '#60A8A0', // warm teal
    '#C8B070', // ochre gold
    '#A87868', // terracotta
    '#A0B890', // dusty sage
]

/**
 * Fix common LLM mistake: N cartesian series each with 1 data point
 * when there are N xAxis categories. Merges them into a single series
 * so each bar/line maps correctly to its category.
 *
 * Example broken input:
 *   xAxis.data = ["CPU", "RAM", "Disco"]
 *   series = [{name:"CPU", data:[17]}, {name:"RAM", data:[82]}, {name:"Disco", data:[75]}]
 *
 * Fixed output:
 *   series = [{type:"bar", data:[17, 82, 75]}]  (+ colorBy: "data" for distinct colors)
 */
function fixSingleDataPointSeries(opt: Record<string, unknown>): void {
    const series = opt.series
    if (!Array.isArray(series) || series.length < 2) return

    // Only fix cartesian charts with a category xAxis
    const xAxis = opt.xAxis as Record<string, unknown> | undefined
    if (!xAxis || typeof xAxis !== 'object') return
    const categories = xAxis.data
    if (!Array.isArray(categories)) return

    // Check: all series are the same cartesian type, each has exactly 1 data point
    const allSeries = series as Record<string, unknown>[]
    const chartType = allSeries[0]?.type as string | undefined
    if (!chartType || !['bar', 'line'].includes(chartType)) return

    const allSinglePoint = allSeries.every((s) => {
        const d = s.data
        return (
            s.type === chartType &&
            Array.isArray(d) &&
            d.length === 1
        )
    })

    if (!allSinglePoint || allSeries.length !== categories.length) return

    // Merge into a single series
    const mergedData = allSeries.map((s) => (s.data as unknown[])[0])
    opt.series = [{
        type: chartType,
        data: mergedData,
        colorBy: 'data',
    }]

    // Legend is meaningless after merge — remove it
    delete opt.legend
}

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

    // Apply OMNIA palette.
    opt.color = OMNIA_PALETTE

    // Fix common LLM mistake: N cartesian series each with 1 data point
    // for N xAxis categories. Merge them into a single series.
    fixSingleDataPointSeries(opt)

    // Legend: process BEFORE grid so grid.bottom can account for it.
    // Always force legend to bottom-center horizontal — the LLM often places
    // it at top: 'middle' or uses orient: 'vertical', causing it to overlap bars.
    const hasLegend = !!(opt.legend && typeof opt.legend === 'object')
    if (hasLegend) {
        const legend = opt.legend as Record<string, unknown>
        // Sync legend.data with actual series names.
        const optSeries = opt.series
        if (Array.isArray(optSeries)) {
            const seriesNames = (optSeries as Record<string, unknown>[])
                .map((s) => s.name as string | undefined)
                .filter((n): n is string => !!n)
            if (Array.isArray(legend.data) && seriesNames.length > 0) {
                const hasOrphan = (legend.data as string[]).some(
                    (name) => !seriesNames.includes(name),
                )
                if (hasOrphan) {
                    legend.data = seriesNames
                }
            }
        }
        // Force position and orientation — delete any LLM-provided positioning.
        delete legend.top
        delete legend.left
        delete legend.right
        legend.bottom = 8
        legend.orient = 'horizontal'
        legend.type = 'scroll'
        legend.textStyle = { color: '#C8C5BE', fontSize: 12 }
        legend.pageTextStyle = { color: '#8A8A85' }
        legend.pageIconColor = '#E8DCC8'
        legend.pageIconInactiveColor = '#4A4A4A'
    }

    // Grid: generous padding, always containLabel.
    // top is sized to accommodate a yAxis name if present (ECharts places it
    // above the axis and clips it when top is too small).
    // bottom reserves space for the legend so it never overlaps the plot area.
    // Critical: our enforced values come AFTER ...existingGrid so the LLM
    // can't accidentally override containLabel or bottom.
    const existingGrid = (opt.grid ?? {}) as Record<string, unknown>
    const hasAxisName = (() => {
        for (const k of ['xAxis', 'yAxis']) {
            const a = opt[k]
            const axes = Array.isArray(a) ? a : (a && typeof a === 'object' ? [a] : [])
            if ((axes as Record<string, unknown>[]).some((ax) => !!ax.name)) return true
        }
        return false
    })()
    const hasYAxisName = (() => {
        const a = opt.yAxis
        const axes = Array.isArray(a) ? a : (a && typeof a === 'object' ? [a] : [])
        return (axes as Record<string, unknown>[]).some((ax) => !!ax.name)
    })()
    opt.grid = {
        top: hasAxisName ? 36 : (hadTitle ? 24 : 14),
        right: 20,
        left: hasYAxisName ? 20 : 14,
        ...existingGrid,
        bottom: hasLegend ? 56 : 16,
        containLabel: true,
    }

    // Use transparent background so the container CSS surface color shows through.
    opt.backgroundColor = 'transparent'

    // Style tooltip — matches --surface-3 (#2A2A2A) and --text-primary (#EDEDE9).
    opt.tooltip = {
        ...(typeof opt.tooltip === 'object' && opt.tooltip ? opt.tooltip : {}),
        backgroundColor: 'rgba(42, 42, 42, 0.97)',
        borderColor: 'rgba(255, 255, 255, 0.08)',
        borderWidth: 1,
        textStyle: { color: '#EDEDE9', fontSize: 13 },
        extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.04);',
    } as Record<string, unknown>

    // Style axes — use --border and warm-gray text matching the app.
    for (const axisKey of ['xAxis', 'yAxis']) {
        const axis = opt[axisKey]
        const axes = Array.isArray(axis) ? axis : (axis && typeof axis === 'object' ? [axis] : [])
        for (const ax of axes as Record<string, unknown>[]) {
            ax.axisLine = { lineStyle: { color: 'rgba(255,255,255,0.08)' } }
            ax.axisTick = { lineStyle: { color: 'rgba(255,255,255,0.08)' } }
            ax.axisLabel = {
                ...(typeof ax.axisLabel === 'object' && ax.axisLabel ? ax.axisLabel : {}),
                color: '#8A8A85',
                fontSize: 12,
            }
            ax.splitLine = { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } }

            if (ax.name) {
                // nameLocation 'end' (default) puts the label at the top of yAxis
                // where it clips. 'middle' centres it along the axis and is always
                // fully visible. nameGap shifts it away from the tick labels.
                if (axisKey === 'yAxis') {
                    ax.nameLocation = 'middle'
                    ax.nameRotate = 90
                    ax.nameGap = 48
                } else {
                    ax.nameLocation = 'middle'
                    ax.nameGap = 28
                }
                ax.nameTextStyle = { color: '#C8C5BE', fontSize: 12 }
            }
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

                const serType = ser.type as string | undefined

                // ── Cartesian labels (bar / line) ──
                // LLMs often place label show:true with position 'bottom'
                // or inside, which overlaps with xAxis category labels.
                // Force them above bars with proper dark-theme styling.
                if (serType === 'bar' || serType === 'line') {
                    if (ser.label && typeof ser.label === 'object') {
                        const lbl = ser.label as Record<string, unknown>
                        if (lbl.show) {
                            lbl.position = 'top'
                            lbl.color = '#C8C5BE'
                            lbl.fontSize = 11
                            lbl.fontWeight = 500
                            delete lbl.backgroundColor
                            delete lbl.borderColor
                            delete lbl.borderWidth
                            delete lbl.padding
                            delete lbl.borderRadius
                        }
                    }
                    // Also fix labels embedded inside individual data items
                    if (Array.isArray(ser.data)) {
                        for (const d of ser.data) {
                            if (d && typeof d === 'object' && !Array.isArray(d)) {
                                const item = d as Record<string, unknown>
                                if (item.label && typeof item.label === 'object') {
                                    const il = item.label as Record<string, unknown>
                                    if (il.show) {
                                        il.position = 'top'
                                        il.color = '#C8C5BE'
                                        il.fontSize = 11
                                        il.fontWeight = 500
                                        delete il.backgroundColor
                                        delete il.borderColor
                                        delete il.borderWidth
                                        delete il.padding
                                        delete il.borderRadius
                                    }
                                }
                            }
                        }
                    }
                }

                // ── Pie / donut labels ──
                // Force a coherent dark-theme style: muted leader lines,
                // warm-gray text, no ugly default white-on-dark labels.
                if (serType === 'pie') {
                    ser.label = {
                        ...(typeof ser.label === 'object' && ser.label
                            ? ser.label
                            : {}),
                        color: '#C8C5BE',
                        fontSize: 12,
                        fontWeight: 500,
                        fontFamily: 'var(--font-sans)',
                    } as Record<string, unknown>
                    ser.labelLine = {
                        ...(typeof ser.labelLine === 'object' && ser.labelLine
                            ? ser.labelLine
                            : {}),
                        lineStyle: {
                            color: 'rgba(200, 197, 190, 0.3)',
                            width: 1,
                        },
                        smooth: 0.2,
                        length: 12,
                        length2: 16,
                    } as Record<string, unknown>
                    // Ensure emphasis label is styled too
                    ser.emphasis = {
                        ...(typeof ser.emphasis === 'object' && ser.emphasis
                            ? ser.emphasis
                            : {}),
                        label: {
                            color: '#EDEDE9',
                            fontSize: 13,
                            fontWeight: 600,
                        },
                    } as Record<string, unknown>
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

        // Do NOT use ECharts' built-in 'dark' theme — its navy background
        // (#100C2A) conflicts with OMNIA's warm-dark surfaces. We style
        // everything manually and set backgroundColor: 'transparent' so the
        // container CSS background shows through correctly.
        instance = echarts.init(containerRef.value)
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
