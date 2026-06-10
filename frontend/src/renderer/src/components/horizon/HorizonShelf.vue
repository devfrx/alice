<script setup lang="ts">
/**
 * HorizonShelf — the modules living just below the line: one mono medallion
 * per artifact (I · GRAFICO …) plus PIANO n/m when a plan exists. A
 * persistent presence, not a menu: click summons the stage / pins the plan.
 * While the stage is open the shelf doubles as its index (active = gold).
 */
import { artifactLabel, type HorizonArtifact } from '../../composables/horizon/horizonArtifacts'
import { toRoman } from '../../composables/horizon/horizonScene'

withDefaults(
  defineProps<{
    artifacts: HorizonArtifact[]
    planTotal?: number
    planCompleted?: number
    /** Artifact shown on the open stage (gold); null = stage closed. */
    activeArtifactIndex?: number | null
    planPinned?: boolean
  }>(),
  { planTotal: 0, planCompleted: 0, activeArtifactIndex: null, planPinned: false }
)

const emit = defineEmits<{
  'open-artifact': [index: number]
  'toggle-plan': []
}>()
</script>

<template>
  <div v-if="artifacts.length > 0 || planTotal > 0" class="hz-shelf" aria-label="Moduli">
    <button
      v-for="(a, i) in artifacts"
      :key="i"
      class="hz-shelf__item"
      :class="{ 'hz-shelf__item--active': i === activeArtifactIndex }"
      :title="`Apri ${artifactLabel(a.kind).toLowerCase()}`"
      @click="emit('open-artifact', i)"
    >
      {{ toRoman(i + 1) }} · {{ artifactLabel(a.kind) }}
    </button>
    <button
      v-if="planTotal > 0"
      class="hz-shelf__item"
      :class="{ 'hz-shelf__item--active': planPinned }"
      title="Mostra il piano"
      @click="emit('toggle-plan')"
    >
      PIANO {{ planCompleted }}/{{ planTotal }}
    </button>
  </div>
</template>

<style scoped>
.hz-shelf {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  animation: hz-shelf-breathe var(--hz-breath) ease-in-out infinite;
}

.hz-shelf__item {
  border: none;
  background: transparent;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.25em;
  color: var(--hz-ink-faint);
  cursor: pointer;
  transition: color var(--hz-fade) ease;
}

.hz-shelf__item:hover {
  color: var(--hz-ink);
}

.hz-shelf__item--active {
  color: var(--hz-gold);
}

@keyframes hz-shelf-breathe {
  0%,
  100% {
    opacity: 0.85;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hz-shelf {
    animation: none;
  }
}
</style>
