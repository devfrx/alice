<script setup lang="ts">
/**
 * CADGenerationPlaceholder.vue — Loading placeholder for in-progress 3D
 * generation (cad_generate / cad_generate_from_image).
 *
 * Renders a wireframe orb pulse, a localized status message and a small
 * spinner. Designed to overlay or replace the 3D canvas during generation
 * so the user has continuous visual feedback while TRELLIS runs.
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
            <p v-if="!compact" class="cad-gen__hint">Questo può richiedere alcuni minuti</p>
            <AliceSpinner :size="compact ? 'xs' : 'sm'" variant="dots" />
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

@media (prefers-reduced-motion: reduce) {

    .cad-gen__pulse,
    .cad-gen__pulse--delayed {
        animation: none;
    }
}
</style>
