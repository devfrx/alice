<script setup lang="ts">
/**
 * Mono runtime colophon: local model readiness, memory count, services health,
 * RAG readiness. Real signals only. Loads memory stats on mount if missing.
 */
import { computed, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useServicesStore } from '../../stores/services'
import { useMemoryStore } from '../../stores/memory'

type Tone = 'ok' | 'warn' | 'muted'
interface ColophonItem {
  label: string
  value: string
  tone: Tone
}

const settingsStore = useSettingsStore()
const servicesStore = useServicesStore()
const memoryStore = useMemoryStore()

onMounted(() => {
  if (!memoryStore.stats) void memoryStore.loadStats()
})

const modelItem = computed<ColophonItem>(() => {
  const ready = settingsStore.lmStudioConnected && settingsStore.activeModel
  return {
    label: 'modello locale',
    value: ready ? `${settingsStore.activeModel?.name} pronto` : 'non pronto',
    tone: ready ? 'ok' : 'warn'
  }
})

const memoryItem = computed<ColophonItem>(() => {
  const total = memoryStore.stats?.total ?? 0
  return { label: 'memoria', value: `${total} ricordi`, tone: 'muted' }
})

const servicesItem = computed<ColophonItem>(() => ({
  label: 'servizi',
  value: servicesStore.hasDegraded ? 'attenzione' : 'attivi',
  tone: servicesStore.hasDegraded ? 'warn' : 'ok'
}))

const ragItem = computed<ColophonItem>(() => {
  const ready = servicesStore.knowledge?.ready ?? false
  return { label: 'rag', value: ready ? 'pronto' : 'non pronto', tone: ready ? 'ok' : 'muted' }
})

const items = computed<ColophonItem[]>(() => [
  modelItem.value,
  memoryItem.value,
  servicesItem.value,
  ragItem.value
])
</script>

<template>
  <footer class="hcol">
    <span v-for="item in items" :key="item.label" class="hcol__item">
      <span class="hcol__dot" :class="`hcol__dot--${item.tone}`" aria-hidden="true" />
      <b class="hcol__label">{{ item.label }}</b>
      <span class="hcol__value">· {{ item.value }}</span>
    </span>
  </footer>
</template>

<style scoped>
.hcol {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-5);
  margin-top: var(--space-12);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  letter-spacing: var(--tracking-normal);
  color: var(--text-muted);
}

.hcol__item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
}

.hcol__dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
}

.hcol__dot--ok {
  background: var(--success);
}

.hcol__dot--warn {
  background: var(--warning);
}

.hcol__dot--muted {
  background: var(--text-muted);
}

.hcol__label {
  color: var(--text-secondary);
  font-weight: var(--weight-medium);
}
</style>
