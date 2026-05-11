<script setup lang="ts">
/**
 * AmbientBackground.vue — state-aware atmospheric layer.
 * Keeps the page background alive with restrained CSS gradients, waves,
 * and sparse motes that inherit the current AL\CE state.
 */
import { computed } from 'vue'

type AmbientState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'

const props = withDefaults(defineProps<{
    state: AmbientState
    audioLevel: number
    subtle?: boolean
}>(), {
    subtle: false
})

const motes = Array.from({ length: 18 }, (_, index) => ({
    index,
    delay: `${(index * 1.37) % 9}s`,
    duration: `${15 + (index * 2.1) % 11}s`,
    x: `${(index * 19 + 11) % 100}%`,
    y: `${(index * 23 + 7) % 100}%`,
    size: `${1.2 + (index % 5) * 0.45}px`,
    opacity: `${0.10 + (index % 4) * 0.045}`,
}))

function clamp01(value: number): number {
    return Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0))
}

const ambientStyle = computed<Record<string, string>>(() => {
    const audio = clamp01(props.audioLevel)
    return {
        '--ambient-opacity': (0.50 + audio * 0.12).toFixed(3),
        '--ambient-scale': (1 + audio * 0.035).toFixed(3),
    }
})
</script>

<template>
    <div class="ambient" :class="[`ambient--${state}`, { 'ambient--subtle': subtle }]" :style="ambientStyle"
        aria-hidden="true">
        <div class="ambient__mesh" />
        <div class="ambient__flow" />

        <div class="ambient__particles">
            <span v-for="mote in motes" :key="mote.index" class="ambient__particle" :style="{
                '--delay': mote.delay,
                '--duration': mote.duration,
                '--x-start': mote.x,
                '--y-start': mote.y,
                '--size': mote.size,
                '--opacity': mote.opacity,
            }" />
        </div>

        <div class="ambient__waves">
            <div class="ambient__wave ambient__wave--1" />
            <div class="ambient__wave ambient__wave--2" />
            <div class="ambient__wave ambient__wave--3" />
        </div>

        <div class="ambient__grain" />
    </div>
</template>

<style scoped>
.ambient {
    --ambient-primary: rgba(232, 220, 200, 0.055);
    --ambient-secondary: rgba(160, 200, 192, 0.035);
    --ambient-tertiary: rgba(218, 198, 168, 0.032);
    --ambient-line: rgba(232, 220, 200, 0.13);
    --ambient-particle: rgba(232, 220, 200, 0.50);
    --ambient-flow-speed: 28s;
    --ambient-wave-speed: 12s;
    position: absolute;
    inset: 0;
    z-index: 0;
    overflow: hidden;
    isolation: isolate;
    pointer-events: none;
    background: var(--surface-0);
    transition: background 700ms var(--ease-smooth);
}

.ambient--listening {
    --ambient-primary: rgba(224, 96, 96, 0.070);
    --ambient-secondary: rgba(232, 184, 128, 0.036);
    --ambient-tertiary: rgba(160, 92, 92, 0.035);
    --ambient-line: rgba(238, 112, 102, 0.15);
    --ambient-particle: rgba(255, 194, 178, 0.52);
    --ambient-flow-speed: 20s;
    --ambient-wave-speed: 7.4s;
}

.ambient--thinking {
    --ambient-primary: rgba(168, 188, 218, 0.065);
    --ambient-secondary: rgba(232, 220, 200, 0.038);
    --ambient-tertiary: rgba(110, 155, 215, 0.032);
    --ambient-line: rgba(190, 204, 230, 0.14);
    --ambient-particle: rgba(218, 228, 242, 0.50);
    --ambient-flow-speed: 24s;
    --ambient-wave-speed: 9.5s;
}

.ambient--speaking {
    --ambient-primary: rgba(92, 154, 110, 0.060);
    --ambient-secondary: rgba(232, 184, 128, 0.040);
    --ambient-tertiary: rgba(80, 185, 165, 0.030);
    --ambient-line: rgba(148, 206, 166, 0.13);
    --ambient-particle: rgba(170, 220, 180, 0.50);
    --ambient-flow-speed: 22s;
    --ambient-wave-speed: 8.2s;
}

.ambient--processing {
    --ambient-primary: rgba(182, 244, 255, 0.058);
    --ambient-secondary: rgba(246, 245, 240, 0.044);
    --ambient-tertiary: rgba(170, 160, 220, 0.034);
    --ambient-line: rgba(206, 236, 246, 0.15);
    --ambient-particle: rgba(226, 244, 250, 0.56);
    --ambient-flow-speed: 18s;
    --ambient-wave-speed: 6.8s;
}

.ambient--subtle {
    opacity: 0.58;
}

.ambient__mesh,
.ambient__flow,
.ambient__particles,
.ambient__waves,
.ambient__grain {
    position: absolute;
    inset: 0;
}

.ambient__mesh {
    background:
        radial-gradient(ellipse at 42% 36%, var(--ambient-primary) 0%, transparent 48%),
        radial-gradient(ellipse at 64% 58%, var(--ambient-secondary) 0%, transparent 52%),
        radial-gradient(ellipse at 28% 74%, var(--ambient-tertiary) 0%, transparent 46%);
    filter: blur(18px) saturate(1.05);
    opacity: var(--ambient-opacity);
    transform: scale(var(--ambient-scale));
    animation: ambientMeshDrift 18s var(--ease-smooth) infinite alternate;
    transition:
        background 800ms var(--ease-smooth),
        opacity 700ms var(--ease-smooth),
        transform 700ms var(--ease-smooth);
}

.ambient__flow {
    inset: -18%;
    background:
        conic-gradient(from 90deg at 50% 50%, transparent 0deg, var(--ambient-secondary) 54deg, transparent 126deg, var(--ambient-primary) 214deg, transparent 302deg),
        radial-gradient(ellipse at 50% 52%, transparent 0%, var(--ambient-tertiary) 58%, transparent 74%);
    filter: blur(42px);
    mix-blend-mode: screen;
    opacity: 0.34;
    animation: ambientFlowTurn var(--ambient-flow-speed) linear infinite;
    transition: background 800ms var(--ease-smooth), opacity 700ms var(--ease-smooth);
}

.ambient__wave {
    position: absolute;
    left: -12%;
    right: -12%;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--ambient-line), transparent);
    opacity: 0.38;
    transform-origin: center;
    animation: ambientWaveTravel var(--ambient-wave-speed) var(--ease-smooth) infinite alternate;
}

.ambient__wave--1 {
    top: 32%;
    transform: rotate(-9deg);
}

.ambient__wave--2 {
    top: 56%;
    animation-delay: -4s;
    transform: rotate(6deg);
}

.ambient__wave--3 {
    top: 78%;
    animation-delay: -8s;
    opacity: 0.24;
    transform: rotate(-3deg);
}

.ambient__particles {
    opacity: 0.72;
    transition: opacity 700ms var(--ease-smooth);
}

.ambient--subtle .ambient__particles,
.ambient--subtle .ambient__waves {
    opacity: 0.36;
}

.ambient__particle {
    position: absolute;
    left: var(--x-start);
    top: var(--y-start);
    width: var(--size);
    height: var(--size);
    border-radius: var(--radius-full);
    background: var(--ambient-particle);
    opacity: 0;
    box-shadow: 0 0 10px var(--ambient-particle);
    animation: ambientParticle var(--duration) var(--ease-smooth) infinite;
    animation-delay: var(--delay);
}

.ambient__grain {
    opacity: 0.18;
    background-image: radial-gradient(rgba(255, 255, 255, 0.08) 0.7px, transparent 0.7px);
    background-size: 28px 28px;
    mask-image: radial-gradient(ellipse at center, black 0%, transparent 72%);
}

@keyframes ambientMeshDrift {
    from {
        transform: translate3d(-1.2%, -0.8%, 0) scale(var(--ambient-scale));
    }

    to {
        transform: translate3d(1.4%, 1.0%, 0) scale(var(--ambient-scale));
    }
}

@keyframes ambientFlowTurn {
    to {
        transform: rotate(360deg);
    }
}

@keyframes ambientWaveTravel {
    from {
        translate: -2% 0;
        opacity: 0.22;
    }

    to {
        translate: 2% 0;
        opacity: 0.42;
    }
}

@keyframes ambientParticle {
    0%,
    100% {
        transform: translate3d(-12px, 10px, 0) scale(0.5);
        opacity: 0;
    }

    42% {
        opacity: var(--opacity);
    }

    66% {
        transform: translate3d(18px, -18px, 0) scale(1);
        opacity: var(--opacity);
    }
}

@media (prefers-reduced-motion: reduce) {
    .ambient__mesh,
    .ambient__flow,
    .ambient__wave,
    .ambient__particle {
        animation: none;
    }
}
</style>
