<script setup lang="ts">
/** HorizonMasthead — the folio: AL\CE wordmark + connection glyph. */
defineProps<{ connected: boolean }>()
</script>

<template>
  <div class="hz-masthead">
    <span class="hz-masthead__folio">AL\CE</span>
    <span
      class="hz-masthead__status"
      :class="{ 'hz-masthead__status--off': !connected }"
      :title="connected ? 'Connessa' : 'Disconnessa'"
    />
  </div>
</template>

<style scoped>
.hz-masthead {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding-top: clamp(20px, 4vh, 44px);
  user-select: none;
}

.hz-masthead__folio {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.42em;
  text-indent: 0.42em; /* optically recenters the tracked text */
  color: var(--hz-ink-faint);
}

.hz-masthead__status {
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--success);
  opacity: 0.7;
}

.hz-masthead__status--off {
  background: var(--danger);
  animation: hz-blink 2s ease-in-out infinite;
}

@keyframes hz-blink {
  50% {
    opacity: 0.25;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hz-masthead__status--off {
    animation: none;
  }
}
</style>
