<script setup lang="ts">
/**
 * AmbientBackground.vue — state-aware atmospheric layer.
 * Flat surface-0 background with a single faint, state-tinted radial glow
 * centred behind the orb. No animations other than a colour transition.
 */
import { computed } from 'vue'

type AmbientState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'

const props = withDefaults(
  defineProps<{
    state: AmbientState
    audioLevel: number
    subtle?: boolean
  }>(),
  {
    subtle: false
  }
)

const glowStyle = computed(() => {
  const color =
    props.state === 'listening'
      ? 'var(--listening)'
      : props.state === 'thinking'
        ? 'var(--thinking)'
        : props.state === 'speaking'
          ? 'var(--speaking)'
          : props.state === 'processing'
            ? 'var(--info)'
            : 'var(--accent)'
  return { '--ambient-orb': color } as Record<string, string>
})
</script>

<template>
  <div class="ambient" :class="`ambient--${props.state}`" aria-hidden="true">
    <div class="ambient__orb-glow" :style="glowStyle" />
  </div>
</template>

<style scoped>
.ambient {
  position: absolute;
  inset: 0;
  z-index: 0;
  background: var(--surface-0);
  overflow: hidden;
}

.ambient__orb-glow {
  position: absolute;
  top: 32%;
  left: 50%;
  width: min(70vw, 620px);
  height: min(70vw, 620px);
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: radial-gradient(
    circle,
    color-mix(in srgb, var(--ambient-orb, var(--accent)) var(--orb-glow-alpha), transparent) 0%,
    transparent 65%
  );
  filter: blur(28px);
  transition: background 600ms var(--ease-smooth, ease);
  pointer-events: none;
}

@media (prefers-reduced-motion: reduce) {
  .ambient__orb-glow {
    transition: none;
  }
}
</style>
