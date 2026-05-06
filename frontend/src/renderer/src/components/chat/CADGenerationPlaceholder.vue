<script setup lang="ts">
/**
 * CADGenerationPlaceholder.vue — Loading placeholder for in-progress 3D
 * generation (cad_generate / cad_generate_from_image).
 *
 * Renders a wireframe orb pulse, a localized status message and a small
 * spinner. Designed to overlay or replace the 3D canvas during generation
 * so the user has continuous visual feedback while TRELLIS runs.
 *
 * When the backend forwards ``tool_progress`` frames (currently only
 * TRELLIS.2 image-to-3D), the placeholder also renders a determinate
 * progress bar with the active sampling stage label.
 *
 * Theming is fully driven by CSS custom properties — no hardcoded colors.
 */
import { computed } from 'vue'
import AliceSpinner from '../ui/AliceSpinner.vue'
import AppIcon from '../ui/AppIcon.vue'
import type { CadGenerationInfo } from '../../composables/useGenerationState'

const props = withDefaults(
    defineProps<{
        /** Active CAD generation descriptor. */
        generation: CadGenerationInfo
        /** Compact variant for inline usage inside chat bubbles. */
        compact?: boolean
    }>(),
    { compact: false },
)

const heading = computed(() =>
    props.generation.toolName === 'cad_generate_from_image'
        ? "Generazione modello 3D dall'immagine…"
        : 'Generazione modello 3D dal testo…',
)

/** True while the backend has emitted at least one progress frame. */
const hasProgress = computed(
    () => typeof props.generation.progress?.percent === 'number',
)

/** Clamped percent value used for the progress bar fill. */
const percent = computed(() => {
    const p = props.generation.progress?.percent
    if (typeof p !== 'number') return 0
    return Math.max(0, Math.min(100, Math.round(p)))
})

/** Localised label for the current pipeline stage. */
const stageLabel = computed(() => {
    const phase = props.generation.progress?.phase
    if (phase === 'postprocess') return 'Finalizzazione mesh…'
    if (phase === 'done') return 'Completato'
    const raw = props.generation.progress?.label
    if (raw) return `Stage: ${raw}`
    if (phase === 'init') return 'Inizializzazione…'
    return null
})

/** Optional "n/m" step counter for the active stage. */
const stepCounter = computed(() => {
    const p = props.generation.progress
    if (!p || typeof p.step !== 'number' || typeof p.total !== 'number') return null
    if (p.total <= 0) return null
    return `${p.step}/${p.total}`
})

/** Wall-clock elapsed since generation started, formatted as ``mm:ss``. */
const elapsed = computed(() => {
    const s = props.generation.progress?.elapsedS
    if (typeof s !== 'number' || s <= 0) return null
    const total = Math.floor(s)
    const mins = Math.floor(total / 60)
    const secs = total % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
})
</script>

<template>
    <div class="cad-gen" :class="{ 'cad-gen--compact': compact }" role="status" :aria-label="heading">
        <div class="cad-gen__orb" aria-hidden="true">
            <AppIcon name="box-3d" :size="compact ? 22 : 38" />
            <span class="cad-gen__pulse" />
            <span class="cad-gen__pulse cad-gen__pulse--delayed" />
        </div>

        <div class="cad-gen__text">
            <p class="cad-gen__heading">{{ heading }}</p>

            <!-- Determinate progress bar (only when backend reports progress) -->
            <div
                v-if="hasProgress"
                class="cad-gen__progress"
                role="progressbar"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-valuenow="percent"
            >
                <div class="cad-gen__progress-track">
                    <div class="cad-gen__progress-fill" :style="{ width: percent + '%' }" />
                </div>
                <div class="cad-gen__progress-meta">
                    <span class="cad-gen__progress-percent">{{ percent }}%</span>
                    <span v-if="stageLabel" class="cad-gen__progress-stage">{{ stageLabel }}</span>
                    <span v-if="stepCounter" class="cad-gen__progress-step">{{ stepCounter }}</span>
                    <span v-if="elapsed" class="cad-gen__progress-elapsed">{{ elapsed }}</span>
                </div>
            </div>

            <template v-else>
                <p v-if="!compact" class="cad-gen__hint">Questo può richiedere alcuni minuti</p>
                <AliceSpinner :size="compact ? 'xs' : 'sm'" variant="dots" />
            </template>
        </div>
    </div>
</template>

<style scoped>
.cad-gen {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-5);
    padding: var(--space-6);
    background: var(--surface-0);
    color: var(--text-primary);
    z-index: 2;
    pointer-events: none;
    text-align: center;
}

.cad-gen--compact {
    position: relative;
    inset: auto;
    height: 200px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface-1);
    gap: var(--space-3);
    padding: var(--space-4);
}

.cad-gen__orb {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 96px;
    height: 96px;
    border-radius: 50%;
    background: var(--accent-dim);
    border: 1px solid var(--accent-border);
    color: var(--accent);
    box-shadow: inset 0 0 32px var(--accent-glow);
}

.cad-gen--compact .cad-gen__orb {
    width: 56px;
    height: 56px;
}

.cad-gen__pulse {
    position: absolute;
    inset: -4px;
    border-radius: 50%;
    border: 1px solid var(--accent-border);
    opacity: 0.6;
    animation: cad-gen-pulse 2.4s ease-out infinite;
}

.cad-gen__pulse--delayed {
    animation-delay: 1.2s;
}

@keyframes cad-gen-pulse {
    0% {
        transform: scale(0.85);
        opacity: 0.7;
    }

    80% {
        transform: scale(1.6);
        opacity: 0;
    }

    100% {
        transform: scale(1.6);
        opacity: 0;
    }
}

.cad-gen__text {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
}

.cad-gen__heading {
    margin: 0;
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-primary);
    letter-spacing: 0.02em;
}

.cad-gen--compact .cad-gen__heading {
    font-size: var(--text-xs);
}

.cad-gen__hint {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--text-muted);
    font-family: var(--font-mono);
    letter-spacing: 0.04em;
}

/* Determinate progress bar (driven by tool_progress WS frames). */
.cad-gen__progress {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: var(--space-2);
    width: min(360px, 80%);
    margin-top: var(--space-2);
}

.cad-gen--compact .cad-gen__progress {
    width: 100%;
    gap: var(--space-1);
    margin-top: var(--space-1);
}

.cad-gen__progress-track {
    position: relative;
    width: 100%;
    height: 6px;
    border-radius: 999px;
    background: var(--surface-2);
    overflow: hidden;
}

.cad-gen__progress-fill {
    position: absolute;
    inset: 0 auto 0 0;
    height: 100%;
    background: linear-gradient(
        90deg,
        var(--accent) 0%,
        var(--accent-strong, var(--accent)) 100%
    );
    border-radius: inherit;
    transition: width 220ms ease-out;
    box-shadow: 0 0 12px var(--accent-glow);
}

.cad-gen__progress-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    color: var(--text-muted);
    font-family: var(--font-mono);
    letter-spacing: 0.04em;
}

.cad-gen__progress-percent {
    color: var(--text-primary);
    font-weight: var(--weight-medium);
}

.cad-gen__progress-stage {
    color: var(--text-secondary, var(--text-primary));
}

.cad-gen__progress-step,
.cad-gen__progress-elapsed {
    color: var(--text-muted);
}

@media (prefers-reduced-motion: reduce) {

    .cad-gen__pulse,
    .cad-gen__pulse--delayed {
        animation: none;
    }
}
</style>
