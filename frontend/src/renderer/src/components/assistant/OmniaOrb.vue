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
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    /* Allow glow to extend beyond bounds */
    overflow: visible;
}

.neural-orb:hover {
    transform: scale(1.03);
}

.neural-orb:active {
    transform: scale(0.97);
}

.neural-orb:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 8px;
    border-radius: 50%;
}

.neural-orb__canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
}

/* State-specific breathing animations on the container */
.neural-orb--idle {
    animation: nn-breathe-idle 5s ease-in-out infinite;
}

.neural-orb--listening {
    animation: nn-breathe-listen 2s ease-in-out infinite;
}

.neural-orb--thinking {
    animation: nn-breathe-think 3s ease-in-out infinite;
}

.neural-orb--speaking {
    animation: nn-breathe-speak 2.5s ease-in-out infinite;
}

.neural-orb--processing {
    animation: nn-breathe-process 1.5s ease-in-out infinite;
}

@keyframes nn-breathe-idle {

    0%,
    100% {
        transform: scale(1);
    }

    50% {
        transform: scale(1.012);
    }
}

@keyframes nn-breathe-listen {

    0%,
    100% {
        transform: scale(1);
    }

    50% {
        transform: scale(1.025);
    }
}

@keyframes nn-breathe-think {

    0%,
    100% {
        transform: scale(1);
    }

    50% {
        transform: scale(1.018);
    }
}

@keyframes nn-breathe-speak {

    0%,
    100% {
        transform: scale(1);
    }

    30% {
        transform: scale(1.022);
    }

    70% {
        transform: scale(0.99);
    }
}

@keyframes nn-breathe-process {

    0%,
    100% {
        transform: scale(1);
    }

    50% {
        transform: scale(1.015);
    }
}
</style>
