<script setup lang="ts">
/**
 * HorizonScene — the stage. Owns the vertical zoning (masthead / upper /
 * lower) and animates the content quota between scene states: that movement
 * IS the visible morph. The backdrop slot hosts the neural network
 * (HorizonNeural), full-bleed under the content zones. Pure layout: no stores.
 */
import { computed } from 'vue'
import type { HorizonState } from '../../composables/horizon/horizonScene'

const props = withDefaults(
  defineProps<{
    state: HorizonState
    /** Long-response magazine layout (overrides the state quota). */
    magazine?: boolean
    /** Dim the whole scene (a dialog is in front). */
    dimmed?: boolean
  }>(),
  { magazine: false, dimmed: false }
)

/** Content quota per state (fraction of scene height). */
const QUOTAS: Record<HorizonState, number> = {
  quiet: 0.58,
  listening: 0.6,
  thinking: 0.6,
  responding: 0.64,
  working: 0.5
}

const quota = computed(() => (props.magazine ? 0.18 : QUOTAS[props.state]))
</script>

<template>
  <div
    class="hz-scene"
    :class="[`hz-scene--${state}`, { 'hz-scene--dimmed': dimmed }]"
    :style="{ '--quota': `${quota * 100}%` }"
  >
    <slot name="backdrop" />
    <header class="hz-scene__masthead"><slot name="masthead" /></header>
    <div class="hz-scene__upper"><slot name="upper" /></div>
    <div class="hz-scene__lower"><slot name="lower" /></div>
  </div>
</template>

<style scoped>
.hz-scene {
  position: relative;
  width: 100%;
  height: 100%;
  background:
    radial-gradient(
      120% 85% at 50% 115%,
      rgba(var(--hz-line-rgb), var(--hz-warmth)),
      transparent 60%
    ),
    var(--surface-0);
  overflow: hidden;
  transition: opacity var(--hz-fade) ease;
}

/* Grana carta: pattern CSS puro, nessun asset esterno. */
.hz-scene::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: var(--hz-grain-opacity);
  background-image: repeating-conic-gradient(var(--hz-grain-ink) 0 25%, transparent 0 50%);
  background-size: 3px 3px;
}

/* Vignettatura: chiude la scena ai bordi. */
.hz-scene::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: radial-gradient(
    120% 100% at 50% 45%,
    transparent 60%,
    rgba(0, 0, 0, var(--hz-vignette)) 100%
  );
}

.hz-scene--dimmed {
  opacity: 0.4;
  pointer-events: none;
}

.hz-scene__masthead {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 3;
}

.hz-scene__upper {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: var(--quota);
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  z-index: 2;
  transition: height var(--hz-morph) var(--ease-out-expo);
}

.hz-scene__lower {
  position: absolute;
  left: 0;
  right: 0;
  top: var(--quota);
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  z-index: 2;
  padding-top: 44px;
  padding-bottom: clamp(78px, 13vh, 112px); /* clearance for the ground bench (dock + colophon) */
  transition: top var(--hz-morph) var(--ease-out-expo);
}

@media (prefers-reduced-motion: reduce) {
  .hz-scene__upper,
  .hz-scene__lower {
    transition: none;
  }
}
</style>
