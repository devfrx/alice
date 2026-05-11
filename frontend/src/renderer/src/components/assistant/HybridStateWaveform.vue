<script setup lang="ts">
/**
 * HybridStateWaveform.vue — low-profile state field for Hybrid mode.
 *
 * This is intentionally quieter than the Assistant Veil: continuous contour
 * lines and refracted filaments that can sit behind the chat input without
 * reading as a separate widget or equalizer demo.
 */
import { computed } from 'vue'
import type { OrbState } from './veil-orb/types'

const props = withDefaults(defineProps<{
    state: OrbState
    audioLevel: number
    compact?: boolean
}>(), {
    compact: false,
})

const STATE_MOTION: Record<OrbState, { cycle: string; peak: number; drift: string; trace: string }> = {
    idle: { cycle: '5.8s', peak: 0.64, drift: '24s', trace: '18s' },
    listening: { cycle: '1.55s', peak: 1.06, drift: '13s', trace: '9.5s' },
    thinking: { cycle: '2.8s', peak: 0.92, drift: '18s', trace: '12s' },
    speaking: { cycle: '1.42s', peak: 1.12, drift: '12s', trace: '8.8s' },
    processing: { cycle: '1.18s', peak: 1.22, drift: '10s', trace: '7.4s' },
}

const filaments = Array.from({ length: 54 }, (_, index) => {
    const normal = index / 53
    const center = 1 - Math.abs(normal - 0.5) * 2
    const lowWave = Math.sin(index * 0.47) * 0.5 + 0.5
    const highWave = Math.cos(index * 0.19) * 0.5 + 0.5
    return {
        index,
        left: `${(normal * 100).toFixed(2)}%`,
        height: `${Math.round(18 + center * 58 + lowWave * 24 + highWave * 10)}px`,
        delay: `${-(index * 0.057).toFixed(3)}s`,
        opacity: (0.12 + center * 0.28 + lowWave * 0.10).toFixed(3),
        width: index % 7 === 0 ? '2px' : '1px',
    }
})

function clamp01(value: number): number {
    return Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0))
}

const waveformStyle = computed<Record<string, string>>(() => {
    const motion = STATE_MOTION[props.state]
    const audio = clamp01(props.audioLevel)
    return {
        '--wave-cycle': motion.cycle,
        '--wave-peak': Math.min(1.42, motion.peak + audio * 0.26).toFixed(3),
        '--wave-drift': motion.drift,
        '--wave-trace': motion.trace,
        '--wave-audio': audio.toFixed(3),
    }
})
</script>

<template>
    <div class="hybrid-waveform" :class="[`hybrid-waveform--${state}`, { 'hybrid-waveform--compact': compact }]"
        :style="waveformStyle" aria-hidden="true">
        <div class="hybrid-waveform__aura" />
        <svg class="hybrid-waveform__ribbons" viewBox="0 0 720 190" preserveAspectRatio="none" focusable="false">
            <path class="hybrid-waveform__ribbon hybrid-waveform__ribbon--wide" pathLength="1"
                d="M-10 128 C 82 111 124 139 204 118 C 294 94 350 142 432 118 C 532 88 596 126 730 101" />
            <path class="hybrid-waveform__ribbon hybrid-waveform__ribbon--mid" pathLength="1"
                d="M-12 142 C 70 132 132 98 218 124 C 294 146 346 95 430 121 C 514 148 594 116 732 130" />
            <path class="hybrid-waveform__ribbon hybrid-waveform__ribbon--fine" pathLength="1"
                d="M-6 112 C 78 126 132 116 196 105 C 300 87 350 119 442 105 C 536 91 614 114 726 84" />
        </svg>
        <div class="hybrid-waveform__filaments">
            <span v-for="filament in filaments" :key="filament.index" class="hybrid-waveform__filament" :style="{
                '--filament-left': filament.left,
                '--filament-height': filament.height,
                '--filament-delay': filament.delay,
                '--filament-opacity': filament.opacity,
                '--filament-width': filament.width,
            }" />
        </div>
        <div class="hybrid-waveform__shore" />
    </div>
</template>

<style scoped>
.hybrid-waveform {
    --wave-color: rgba(217, 230, 228, 0.68);
    --wave-core: rgba(232, 235, 222, 0.42);
    --wave-haze: rgba(154, 182, 178, 0.19);
    position: relative;
    width: 100%;
    height: 152px;
    overflow: hidden;
    pointer-events: none;
    mask-image: linear-gradient(to bottom, transparent 0%, black 22%, black 84%, transparent 100%);
    -webkit-mask-image: linear-gradient(to bottom, transparent 0%, black 22%, black 84%, transparent 100%);
}

.hybrid-waveform--compact {
    height: 136px;
}

.hybrid-waveform--listening {
    --wave-color: rgba(246, 150, 130, 0.68);
    --wave-core: rgba(250, 198, 178, 0.34);
    --wave-haze: rgba(232, 92, 90, 0.15);
}

.hybrid-waveform--thinking {
    --wave-color: rgba(184, 205, 234, 0.66);
    --wave-core: rgba(214, 224, 238, 0.34);
    --wave-haze: rgba(140, 170, 210, 0.14);
}

.hybrid-waveform--speaking {
    --wave-color: rgba(151, 218, 176, 0.66);
    --wave-core: rgba(197, 236, 209, 0.34);
    --wave-haze: rgba(96, 178, 128, 0.14);
}

.hybrid-waveform--processing {
    --wave-color: rgba(197, 237, 244, 0.72);
    --wave-core: rgba(228, 244, 242, 0.40);
    --wave-haze: rgba(148, 226, 240, 0.17);
}

.hybrid-waveform__aura,
.hybrid-waveform__ribbons,
.hybrid-waveform__filaments,
.hybrid-waveform__shore {
    position: absolute;
    inset: 0;
}

.hybrid-waveform__aura {
    background:
        radial-gradient(ellipse at 50% 88%, var(--wave-haze) 0%, transparent 60%),
        radial-gradient(ellipse at 28% 76%, color-mix(in srgb, var(--wave-core) 64%, transparent) 0%, transparent 44%),
        radial-gradient(ellipse at 74% 72%, color-mix(in srgb, var(--wave-core) 52%, transparent) 0%, transparent 46%);
    filter: blur(12px);
    opacity: calc(0.78 + var(--wave-audio) * 0.18);
    transform-origin: 50% 100%;
    animation: hybridAuraDrift var(--wave-drift) var(--ease-smooth) infinite alternate;
}

.hybrid-waveform__ribbons {
    width: 100%;
    height: 100%;
    opacity: 0.86;
    transform-origin: center bottom;
    animation: hybridRibbonBreathe var(--wave-drift) var(--ease-smooth) infinite;
}

.hybrid-waveform__ribbon {
    fill: none;
    stroke: var(--wave-color);
    stroke-linecap: round;
    stroke-dasharray: 0.18 0.82;
    stroke-dashoffset: 0;
    vector-effect: non-scaling-stroke;
    animation: hybridTraceTravel var(--wave-trace) linear infinite;
}

.hybrid-waveform__ribbon--wide {
    stroke-width: 1.4;
    opacity: 0.34;
    filter: blur(0.35px);
}

.hybrid-waveform__ribbon--mid {
    stroke-width: 1;
    opacity: 0.58;
    animation-delay: -2.6s;
}

.hybrid-waveform__ribbon--fine {
    stroke-width: 0.7;
    opacity: 0.40;
    animation-delay: -5.2s;
}

.hybrid-waveform__filaments {
    inset: auto 4% 8px;
    height: 124px;
    filter: drop-shadow(0 0 10px color-mix(in srgb, var(--wave-color) 30%, transparent));
}

.hybrid-waveform__filament {
    position: absolute;
    left: var(--filament-left);
    bottom: 0;
    width: var(--filament-width);
    height: var(--filament-height);
    border-radius: var(--radius-pill);
    background: linear-gradient(to top, transparent 0%, var(--wave-color) 48%, transparent 100%);
    opacity: calc(var(--filament-opacity) * 1.18);
    transform: translateX(-50%) scaleY(0.45);
    transform-origin: 50% 100%;
    animation: hybridFilamentRise var(--wave-cycle) var(--ease-smooth) infinite;
    animation-delay: var(--filament-delay);
}

.hybrid-waveform__shore {
    top: auto;
    height: 54px;
    background:
        linear-gradient(to bottom, transparent 0%, color-mix(in srgb, var(--wave-core) 34%, transparent) 48%, transparent 100%),
        radial-gradient(ellipse at 50% 72%, color-mix(in srgb, var(--wave-color) 18%, transparent) 0%, transparent 68%);
    filter: blur(10px);
    opacity: 0.80;
    transform: translateY(14px);
}

@keyframes hybridFilamentRise {
    0%,
    100% {
        transform: translateX(-50%) scaleY(0.34);
        opacity: calc(var(--filament-opacity) * 0.62);
    }

    46% {
        transform: translateX(-50%) scaleY(var(--wave-peak));
        opacity: calc(var(--filament-opacity) * 1.45);
    }
}

@keyframes hybridTraceTravel {
    to {
        stroke-dashoffset: -1;
    }
}

@keyframes hybridRibbonBreathe {
    0%,
    100% {
        transform: translateY(5px) scaleY(0.96);
    }

    48% {
        transform: translateY(-3px) scaleY(calc(1 + var(--wave-audio) * 0.08));
    }
}

@keyframes hybridAuraDrift {
    from {
        transform: translateX(-3%) scaleX(0.96);
    }

    to {
        transform: translateX(3%) scaleX(1.04);
    }
}

@media (prefers-reduced-motion: reduce) {
    .hybrid-waveform__aura,
    .hybrid-waveform__ribbons,
    .hybrid-waveform__ribbon,
    .hybrid-waveform__filament {
        animation: none;
    }
}
</style>
