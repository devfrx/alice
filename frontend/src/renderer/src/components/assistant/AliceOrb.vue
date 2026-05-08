<script setup lang="ts">
/**
 * AliceOrb.vue — The Veil
 *
 * Renders the AL\CE presence as a small living drape: a stack of translucent
 * silk sheets in front of a pearl core, lit by a restrained vertical light
 * shaft from above (a direct nod to the brand portrait).
 *
 * Each state owns its own *mechanic* (audio wave, helical twist, warm bloom,
 * precision glint, sparse motes) — not just a different palette — so the assistant
 * stays legible at a glance. State transitions trigger a destination-specific
 * flourish; click, tool-call, streaming-token and completion events route to
 * dedicated rendering paths.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { VeilEngine } from './veil-orb/engine'
import type { OrbState } from './veil-orb/types'

const props = withDefaults(defineProps<{
    state: OrbState
    audioLevel: number
    compact?: boolean
}>(), {
    compact: false,
})

const emit = defineEmits<{
    click: []
}>()

const isDev = import.meta.env.DEV
const devStateOptions: Array<{ state: OrbState; label: string; title: string }> = [
    { state: 'idle', label: 'I', title: 'Idle' },
    { state: 'listening', label: 'L', title: 'Listening' },
    { state: 'thinking', label: 'T', title: 'Thinking' },
    { state: 'speaking', label: 'S', title: 'Speaking' },
    { state: 'processing', label: 'P', title: 'Processing' },
]

const canvasRef = ref<HTMLCanvasElement | null>(null)
const previewState = ref<OrbState | null>(null)
let engine: VeilEngine | null = null

const containerSize = computed(() => (props.compact ? '172px' : 'clamp(226px, 44vmin, 482px)'))

defineExpose({
    triggerToolCall: (): void => engine?.triggerToolCall(),
    triggerToken: (): void => engine?.triggerToken(),
    triggerDone: (): void => engine?.triggerDone(),
})

onMounted(() => {
    if (!canvasRef.value) return
    engine = new VeilEngine(props.compact)
    engine.init(canvasRef.value)
    engine.setState(props.state)
    engine.setAudioLevel(props.audioLevel)

    /* Dev-only handle for quick visual QA from the browser console. */
    if (isDev) {
        ; (window as unknown as Record<string, unknown>).__veil = {
            setState: (s: OrbState): void => engine?.setState(s),
            audio: (l: number): void => engine?.setAudioLevel(l),
            click: (): void => engine?.triggerClick(),
            token: (): void => engine?.triggerToken(),
            tool: (): void => engine?.triggerToolCall(),
            done: (): void => engine?.triggerDone(),
        }
    }
})

onUnmounted(() => {
    engine?.destroy()
    engine = null
    if (isDev) {
        delete (window as unknown as Record<string, unknown>).__veil
    }
})

watch(() => props.state, (s) => {
    if (!previewState.value) engine?.setState(s)
})
watch(() => props.audioLevel, (l) => {
    if (!previewState.value) engine?.setAudioLevel(l)
})

function startDevPreview(state: OrbState): void {
    if (!isDev) return
    previewState.value = state
    engine?.setState(state)
    engine?.setAudioLevel(state === 'listening' ? Math.max(props.audioLevel, 0.58) : props.audioLevel)
}

function stopDevPreview(): void {
    if (!previewState.value) return
    previewState.value = null
    engine?.setState(props.state)
    engine?.setAudioLevel(props.audioLevel)
}

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
    <div class="alice-orb-shell" :class="{ 'alice-orb-shell--compact': compact }">
        <div class="alice-orb" role="button" tabindex="0"
            :aria-label="state === 'idle' ? 'Clicca per parlare' : `Stato: ${state}`" @click="handleClick"
            @mouseenter="onHoverEnter" @mouseleave="onHoverLeave" @keydown.enter="handleClick"
            @keydown.space.prevent="handleClick">
            <canvas ref="canvasRef" class="alice-orb__canvas" />
        </div>

        <div v-if="isDev" class="alice-orb-dev" aria-label="Dev state preview">
            <button v-for="option in devStateOptions" :key="option.state" class="alice-orb-dev__btn" type="button"
                :class="{ 'alice-orb-dev__btn--active': previewState === option.state }" :title="option.title"
                :aria-label="`Preview ${option.title}`" @pointerdown.stop.prevent="startDevPreview(option.state)"
                @pointerup.stop.prevent="stopDevPreview" @pointerleave.stop="stopDevPreview"
                @pointercancel.stop="stopDevPreview" @blur="stopDevPreview"
                @keydown.enter.stop.prevent="startDevPreview(option.state)" @keyup.enter.stop.prevent="stopDevPreview"
                @keydown.space.stop.prevent="startDevPreview(option.state)" @keyup.space.stop.prevent="stopDevPreview">
                {{ option.label }}
            </button>
        </div>
    </div>
</template>

<style scoped>
.alice-orb-shell {
    position: relative;
    width: v-bind(containerSize);
    height: v-bind(containerSize);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: visible;
}

.alice-orb {
    position: relative;
    width: 100%;
    height: 100%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: visible;
}

.alice-orb:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 8px;
    border-radius: var(--radius-md);
}

.alice-orb__canvas {
    position: absolute;
    top: -22%;
    left: -22%;
    width: 144%;
    height: 144%;
    max-width: none;
    max-height: none;
    aspect-ratio: 1 / 1;
    pointer-events: none;
}

.alice-orb-dev {
    position: absolute;
    top: 50%;
    right: 10px;
    z-index: 2;
    display: inline-flex;
    flex-direction: column;
    gap: 4px;
    padding: 4px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--surface-2) 88%, transparent);
    box-shadow: var(--shadow-xs);
    transform: translateY(-50%);
}

.alice-orb-dev__btn {
    width: 24px;
    height: 22px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid transparent;
    border-radius: calc(var(--radius-sm) - 2px);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    font-weight: var(--weight-semibold);
    letter-spacing: 0;
}

.alice-orb-dev__btn:hover,
.alice-orb-dev__btn--active {
    background: var(--accent-dim);
    border-color: var(--accent-border);
    color: var(--accent);
}

.alice-orb-dev__btn:focus-visible {
    outline: none;
    box-shadow: var(--shadow-focus);
}
</style>
