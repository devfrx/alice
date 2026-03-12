<script setup lang="ts">
/**
 * OmniaOrb.vue  Neural Network Visualization
 *
 * A living neural network simulation replacing the original orb.
 * Canvas-based renderer with state-reactive neurons, synaptic connections,
 * flowing data particles, and smooth state transitions.
 *
 * Same props/events interface as the original orb for drop-in replacement.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { NeuralEngine } from './neural-network/engine'

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
let engine: NeuralEngine | null = null

const containerSize = computed(() => (props.compact ? '160px' : '420px'))

onMounted(() => {
    if (!canvasRef.value) return
    engine = new NeuralEngine(props.compact)
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
    emit('click')
}
</script>

<template>
    <div class="neural-orb" :class="[`neural-orb--${state}`, { 'neural-orb--compact': compact }]" role="button"
        tabindex="0" :aria-label="state === 'idle' ? 'Clicca per parlare' : `Stato: ${state}`" @click="handleClick"
        @keydown.enter="handleClick" @keydown.space.prevent="handleClick">
        <canvas ref="canvasRef" class="neural-orb__canvas" />
    </div>
</template>

<style scoped>
.neural-orb {
    position: relative;
    width: v-bind(containerSize);
    height: v-bind(containerSize);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform var(--transition-normal);
    overflow: visible;
}

.neural-orb:hover {
    transform: scale(1.02);
}

.neural-orb:active {
    transform: scale(0.98);
}

.neural-orb:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 8px;
    border-radius: var(--radius-full);
}

.neural-orb__canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
}

/* State-driven subtle breathing */
.neural-orb--idle {
    animation: orb-breathe 5s ease-in-out infinite;
}

.neural-orb--listening {
    animation: orb-breathe 2s ease-in-out infinite;
}

.neural-orb--thinking {
    animation: orb-breathe 3s ease-in-out infinite;
}

.neural-orb--speaking {
    animation: orb-breathe 2.5s ease-in-out infinite;
}

.neural-orb--processing {
    animation: orb-breathe 1.5s ease-in-out infinite;
}

@keyframes orb-breathe {

    0%,
    100% {
        transform: scale(1);
    }

    50% {
        transform: scale(1.015);
    }
}

@media (prefers-reduced-motion: reduce) {
    .neural-orb {
        transition: none;
    }

    .neural-orb--idle,
    .neural-orb--listening,
    .neural-orb--thinking,
    .neural-orb--speaking,
    .neural-orb--processing {
        animation: none;
    }
}
</style>
