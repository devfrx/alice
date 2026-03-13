<script setup lang="ts">
/**
 * OmniaOrb.vue — Fluid Aurora Orb
 *
 * A living, breathing gradient orb with organic morphing shapes,
 * screen-blended internal light pools, and state-reactive colors.
 * Aesthetic: Anthropic x Supabase — dark, softly glowing, alive.
 *
 * Hover/click/state transitions are fully canvas-driven via FluidEngine
 * using exponential smoothing — no CSS transforms needed.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { FluidEngine } from './fluid-orb/engine'

const props = withDefaults(defineProps<{
    state: 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'
    audioLevel: number
    compact?: boolean
}>(), {
    compact: false,
})

const emit = defineEmits<{
    click: []
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let engine: FluidEngine | null = null

const containerSize = computed(() => (props.compact ? '160px' : '420px'))

onMounted(() => {
    if (!canvasRef.value) return
    engine = new FluidEngine(props.compact)
    engine.init(canvasRef.value)
    engine.setState(props.state)
    engine.setAudioLevel(props.audioLevel)
})

onUnmounted(() => {
    engine?.destroy()
    engine = null
})

watch(() => props.state, (s) => engine?.setState(s))
watch(() => props.audioLevel, (l) => engine?.setAudioLevel(l))

function handleClick(): void {
    engine?.triggerClick()
    emit('click')
}
function onHoverEnter(): void {
    engine?.setHover(true)
}
function onHoverLeave(): void {
    engine?.setHover(false)
}
</script>

<template>
    <div class="omnia-orb" :class="{ 'omnia-orb--compact': compact }" role="button" tabindex="0"
        :aria-label="state === 'idle' ? 'Clicca per parlare' : `Stato: ${state}`" @click="handleClick"
        @mouseenter="onHoverEnter" @mouseleave="onHoverLeave" @keydown.enter="handleClick"
        @keydown.space.prevent="handleClick">
        <canvas ref="canvasRef" class="omnia-orb__canvas" />
    </div>
</template>

<style scoped>
.omnia-orb {
    position: relative;
    width: v-bind(containerSize);
    height: v-bind(containerSize);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: visible;
}

.omnia-orb:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 8px;
    border-radius: var(--radius-full);
}

.omnia-orb__canvas {
    position: absolute;
    inset: -30%;
    width: 160%;
    height: 160%;
    pointer-events: none;
}
</style>
