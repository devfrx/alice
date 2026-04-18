<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ContextInfo } from '../../types/chat'

// SVG circle geometry: r=7, circumference = 2π×7 ≈ 43.98
const CIRC = 43.98

const props = defineProps<{
    contextInfo: ContextInfo | null
    isCompressing: boolean
}>()

// ── Hover state for breakdown tooltip ──────────────────────────────────────
const isHovered = ref(false)
const tooltipPos = ref({ x: 0, y: 0 })
const ctxRef = ref<HTMLElement | null>(null)

function showTooltip() {
    if (!ctxRef.value || !props.contextInfo) return
    const rect = ctxRef.value.getBoundingClientRect()
    tooltipPos.value = {
        x: rect.left + rect.width / 2,
        y: rect.top - 6,
    }
    isHovered.value = true
}

function hideTooltip() {
    isHovered.value = false
}

// ── Ring geometry ──────────────────────────────────────────────────────────
const fillPercent = computed(() => {
    if (!props.contextInfo) return 0
    return Math.min(100, Math.round(props.contextInfo.percentage * 100))
})

const arcDash = computed(() => {
    const filled = (fillPercent.value / 100) * CIRC
    return `${filled.toFixed(2)} ${CIRC}`
})

const fillColor = computed(() => {
    const pct = fillPercent.value
    if (pct >= 95) return 'var(--danger)'
    if (pct >= 85) return 'var(--warning)'
    if (pct >= 60) return 'var(--warning)'
    return 'var(--success)'
})

const shouldPulse = computed(() => fillPercent.value >= 85)
const pulseFast = computed(() => fillPercent.value >= 95)
const prefix = computed(() => (props.contextInfo?.isEstimated ? '~' : ''))

// ── Tooltip content ────────────────────────────────────────────────────────
function formatTokens(n: number): string {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
    return `${n}`
}

const tooltipHeader = computed(() => {
    if (!props.contextInfo) return ''
    const { used, contextWindow, isEstimated } = props.contextInfo
    const pre = isEstimated ? '~' : ''
    return `${pre}${formatTokens(used)} / ${formatTokens(contextWindow)} token`
})

interface BreakdownRow {
    label: string
    tokens: number
    pct: number
    fmt: string
    barPct: number
}

const breakdownRows = computed<BreakdownRow[]>(() => {
    const bd = props.contextInfo?.breakdown
    const cw = props.contextInfo?.contextWindow ?? 0
    if (!bd || cw === 0) return []

    const rows: Array<{ label: string; value: number }> = [
        { label: 'Sistema', value: bd.system },
        { label: 'Tool', value: bd.tools },
        { label: 'Messaggi', value: bd.messages },
        { label: 'File', value: bd.files },
        { label: 'Risultati', value: bd.tool_results },
        { label: 'Altro', value: bd.other },
    ]

    const maxVal = Math.max(1, ...rows.map((r) => r.value))
    return rows
        .filter((r) => r.value > 0)
        .map((r) => ({
            label: r.label,
            tokens: r.value,
            pct: Math.round((r.value / cw) * 100),
            fmt: formatTokens(r.value),
            barPct: Math.round((r.value / maxVal) * 100),
        }))
})

const hasBreakdown = computed(() => breakdownRows.value.length > 0)
</script>

<template>
    <div v-if="contextInfo || isCompressing" ref="ctxRef" class="ctx" @mouseenter="showTooltip"
        @mouseleave="hideTooltip">
        <!-- Compressing state -->
        <template v-if="isCompressing">
            <svg class="ctx__ring ctx__ring--spin" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <circle class="ctx__ring-bg" cx="10" cy="10" r="7" />
                <circle class="ctx__ring-arc" cx="10" cy="10" r="7" stroke="var(--text-muted)" stroke-dasharray="22 44"
                    stroke-dashoffset="0" />
            </svg>
            <span class="ctx__label">Compressione…</span>
        </template>

        <!-- Normal state -->
        <template v-else-if="contextInfo">
            <svg class="ctx__ring" :class="{ 'ctx__ring--pulse': shouldPulse, 'ctx__ring--pulse-fast': pulseFast }"
                viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <circle class="ctx__ring-bg" cx="10" cy="10" r="7" />
                <circle class="ctx__ring-arc" cx="10" cy="10" r="7" :stroke="fillColor" :stroke-dasharray="arcDash"
                    stroke-dashoffset="0" />
            </svg>
            <span class="ctx__pct" :style="{ color: fillPercent >= 60 ? fillColor : 'var(--text-muted)' }">
                {{ prefix }}{{ fillPercent }}%
            </span>
            <span v-if="contextInfo.wasCompressed" class="ctx__compressed" title="Contesto compresso">
                <svg width="7" height="7" viewBox="0 0 8 8" fill="none">
                    <circle cx="4" cy="4" r="3" fill="#C49A3C" />
                </svg>
            </span>
        </template>

        <!-- Breakdown tooltip (teleported to body to escape overflow:hidden) -->
        <Teleport to="body">
            <div v-if="isHovered && contextInfo && !isCompressing" class="alice-ctx-tip"
                :style="{ left: `${tooltipPos.x}px`, top: `${tooltipPos.y}px` }">
                <div class="alice-ctx-tip__header">{{ tooltipHeader }}</div>
                <template v-if="hasBreakdown">
                    <div class="alice-ctx-tip__divider" />
                    <div v-for="row in breakdownRows" :key="row.label" class="alice-ctx-tip__row">
                        <span class="alice-ctx-tip__lbl">{{ row.label }}</span>
                        <div class="alice-ctx-tip__bar-wrap">
                            <div class="alice-ctx-tip__bar"
                                :style="{ width: `${row.barPct}%`, backgroundColor: fillColor }" />
                        </div>
                        <span class="alice-ctx-tip__val">{{ row.fmt }}</span>
                        <span class="alice-ctx-tip__pct">{{ row.pct }}%</span>
                    </div>
                </template>
                <div v-if="contextInfo.isEstimated" class="alice-ctx-tip__note">stima ~</div>
            </div>
        </Teleport>
    </div>
</template>

<style scoped>
.ctx {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 22px;
    flex-shrink: 0;
    cursor: default;
    position: relative;
}

/* ── Ring SVG ── */
.ctx__ring {
    width: 18px;
    height: 18px;
    flex-shrink: 0;
    transform: rotate(-90deg);
    transform-origin: center;
}

.ctx__ring-bg {
    stroke: var(--surface-3);
    stroke-width: 2.2;
    fill: none;
}

.ctx__ring-arc {
    stroke-width: 2.2;
    stroke-linecap: round;
    fill: none;
    transition:
        stroke-dasharray 0.6s cubic-bezier(0.4, 0, 0.2, 1),
        stroke 0.3s ease;
}

.ctx__ring--pulse .ctx__ring-arc {
    animation: ring-pulse 2s ease-in-out infinite;
}

.ctx__ring--pulse-fast .ctx__ring-arc {
    animation: ring-pulse 1s ease-in-out infinite;
}

@keyframes ring-pulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.4;
    }
}

.ctx__ring--spin {
    animation: ring-spin 1s linear infinite;
    transform-origin: center;
}

@keyframes ring-spin {
    from {
        transform: rotate(-90deg);
    }

    to {
        transform: rotate(270deg);
    }
}

/* ── Labels ── */
.ctx__pct {
    font-size: 10px;
    font-weight: var(--weight-medium);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    letter-spacing: 0.01em;
    transition: color 0.3s ease;
}

.ctx__label {
    font-size: 10px;
    color: var(--text-muted);
    white-space: nowrap;
    font-style: italic;
}

.ctx__compressed {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    opacity: 0.8;
}
</style>

<!-- Tooltip styles are NOT scoped (teleported outside component DOM) -->
<style>
.alice-ctx-tip {
    position: fixed;
    z-index: 9999;
    transform: translateX(-50%) translateY(-100%);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 8px 10px;
    min-width: 192px;
    box-shadow: var(--shadow-dropdown);
    pointer-events: none;
    font-size: 11px;
    line-height: 1.4;
}

.alice-ctx-tip__header {
    color: var(--text-primary);
    font-weight: var(--weight-medium);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    padding-bottom: 1px;
}

.alice-ctx-tip__divider {
    height: 1px;
    background: var(--border);
    margin: 5px 0 4px;
}

.alice-ctx-tip__row {
    display: grid;
    grid-template-columns: 64px 1fr 28px 28px;
    align-items: center;
    gap: 4px;
    padding: 1px 0;
}

.alice-ctx-tip__lbl {
    color: var(--text-secondary);
    font-size: 10.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.alice-ctx-tip__bar-wrap {
    height: 3px;
    background: var(--surface-3);
    border-radius: 2px;
    overflow: hidden;
}

.alice-ctx-tip__bar {
    height: 100%;
    border-radius: 2px;
    opacity: 0.65;
    transition: width 0.4s ease;
}

.alice-ctx-tip__val {
    color: var(--text-muted);
    font-size: 10px;
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
}

.alice-ctx-tip__pct {
    color: var(--text-muted);
    font-size: 10px;
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
    opacity: 0.75;
}

.alice-ctx-tip__note {
    margin-top: 5px;
    font-size: 9.5px;
    color: var(--text-muted);
    opacity: 0.6;
    text-align: right;
}
</style>
