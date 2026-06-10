<script setup lang="ts">
/**
 * HorizonColophon — the masthead-style ground line at the bottom of the
 * scene: date · time · next calendar event, plus the disconnected marker.
 * Segments degrade gracefully when a source is unavailable.
 */
import { computed } from 'vue'
import { useClock } from '../../composables/horizon/useClock'
import type { CalendarEvent } from '../../types/calendar'

const props = defineProps<{
  nextEvent: CalendarEvent | null
  connected: boolean
}>()

const now = useClock()

const parts = computed(() => {
  const list: string[] = [
    now.value.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' }),
    now.value.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
  ]
  if (props.nextEvent) {
    const hm = new Date(props.nextEvent.start_time).toLocaleTimeString('it-IT', {
      hour: '2-digit',
      minute: '2-digit'
    })
    list.push(`${props.nextEvent.title} alle ${hm}`)
  }
  if (!props.connected) list.push('DISCONNESSA')
  return list
})
</script>

<template>
  <p class="hz-colophon" :class="{ 'hz-colophon--off': !connected }">
    {{ parts.join(' · ') }}
  </p>
</template>

<style scoped>
.hz-colophon {
  margin: auto 0 clamp(20px, 4vh, 40px);
  font-family: var(--font-sans);
  font-weight: 400;
  font-size: 10px;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
  text-align: center;
  user-select: none;
}

.hz-colophon--off {
  color: var(--danger);
}
</style>
