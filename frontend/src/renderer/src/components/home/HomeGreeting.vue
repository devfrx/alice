<script setup lang="ts">
/**
 * Editorial greeting block: mono kicker (date · runtime) + Fraunces greeting
 * (the ONLY serif element in the app) + a lede built from real counts.
 */
import { computed } from 'vue'
import { useSettingsStore } from '../../stores/settings'
// Local font — bundled by Vite, no CDN. Family name: 'Fraunces'.
import '@fontsource/fraunces/600.css'

const props = defineProps<{ conversationCount: number; memoryCount: number }>()
const settingsStore = useSettingsStore()

// Captured once at mount — the home is re-created on navigation, so a live
// clock is unnecessary churn.
const now = new Date()

const greetingWord = computed<string>(() => {
  const h = now.getHours()
  if (h < 12) return 'Buongiorno'
  if (h < 18) return 'Buon pomeriggio'
  return 'Buonasera'
})

const name = computed<string>(() => settingsStore.settings.llm.userPreferredName?.trim() ?? '')

const dateLabel = computed<string>(() =>
  new Intl.DateTimeFormat('it-IT', { weekday: 'long', day: 'numeric', month: 'long' }).format(now),
)

const lede = computed<string>(() => {
  const c = props.conversationCount
  const m = props.memoryCount
  if (c === 0 && m === 0) return 'Iniziamo da qui. Dimmi su cosa lavoriamo.'
  const parts: string[] = []
  if (c > 0) parts.push(`${c} ${c === 1 ? 'conversazione aperta' : 'conversazioni aperte'}`)
  if (m > 0) parts.push(`${m} ${m === 1 ? 'ricordo' : 'ricordi'} in memoria`)
  return `Hai ${parts.join(' e ')}. Da dove ripartiamo?`
})
</script>

<template>
  <header class="hg">
    <p class="hg__kicker">
      <span class="hg__dot" aria-hidden="true" />
      <span>{{ dateLabel }} · runtime locale</span>
    </p>
    <h1 class="hg__greet">
      {{ greetingWord }}<template v-if="name">, <em>{{ name }}</em></template>.
    </h1>
    <p class="hg__lede">{{ lede }}</p>
  </header>
</template>

<style scoped>
.hg__kicker {
  display: flex;
  align-items: center;
  gap: var(--space-2-5);
  margin: 0 0 var(--space-5);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  letter-spacing: var(--tracking-wide);
  text-transform: uppercase;
}

.hg__dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--success);
  box-shadow: 0 0 8px var(--success-glow);
}

.hg__greet {
  margin: 0 0 var(--space-3);
  /* Fraunces — scoped to this one element. Everything else stays sans. */
  font-family: 'Fraunces', Georgia, serif;
  font-weight: 600;
  font-size: clamp(2.4rem, 4.4vw, 3.4rem);
  line-height: 1.04;
  letter-spacing: -0.015em;
  color: var(--text-primary);
}

.hg__greet em {
  font-style: italic;
  color: var(--accent);
}

.hg__lede {
  max-width: 46ch;
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--text-lg);
  line-height: var(--leading-snug);
}
</style>
