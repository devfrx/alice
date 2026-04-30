<script setup lang="ts">
/**
 * ServicesView — Standalone Service Status & Configuration panel.
 *
 * Lists every managed service (LM Studio, STT, TTS, VRAM, Trellis, …)
 * with a live status badge fed by the events WebSocket and exposes:
 *
 * - Restart / Configure actions per service.
 * - Model download for STT / TTS with WS-driven progress bars.
 * - A dedicated Trellis2 configuration card with directory picker
 *   and a button that opens the in-app setup guide modal.
 */
import { computed, onMounted, ref } from 'vue'
import { useServicesStore } from '../stores/services'
import AppIcon from '../components/ui/AppIcon.vue'
import ServiceCard from '../components/services/ServiceCard.vue'
import TrellisConfigCard from '../components/services/TrellisConfigCard.vue'
import TrellisSetupGuideModal from '../components/services/TrellisSetupGuideModal.vue'

const store = useServicesStore()
const showGuide = ref(false)
const refreshing = ref(false)

onMounted(() => {
  void store.refresh()
  void store.loadCatalog('stt')
  void store.loadCatalog('tts')
})

const stdServices = computed(() =>
  store.services.filter((s) => s.name !== 'trellis' && s.name !== 'trellis2'),
)
const trellisServices = computed(() =>
  store.services.filter((s) => s.name === 'trellis' || s.name === 'trellis2'),
)

const summary = computed(() => {
  const counts = { up: 0, degraded: 0, down: 0, starting: 0 }
  for (const svc of store.services) counts[svc.status] += 1
  return counts
})
const totalServices = computed(() => store.services.length)
const activeDownloads = computed(
  () => Object.values(store.downloads).filter((d) => d.phase === 'downloading').length,
)

async function refreshAll(): Promise<void> {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([
      store.refresh(),
      store.loadCatalog('stt'),
      store.loadCatalog('tts'),
    ])
  } finally {
    refreshing.value = false
  }
}
</script>

<template>
  <main class="services-view">
    <header class="services-view__head">
      <div class="services-view__head-row">
        <div class="services-view__title-block">
          <h1 class="services-view__title">Servizi</h1>
          <p class="services-view__subtitle">
            Stato dei microservizi locali, gestione dei modelli STT/TTS e configurazione 3D.
          </p>
        </div>
        <button
          class="services-view__refresh"
          type="button"
          :disabled="refreshing"
          @click="refreshAll"
        >
          <AppIcon name="refresh-cw" :size="14" :class="{ 'is-spinning': refreshing }" />
          <span>{{ refreshing ? 'Aggiorno…' : 'Aggiorna' }}</span>
        </button>
      </div>

      <div class="services-view__stats">
        <div class="stat-pill stat-pill--up">
          <span class="stat-pill__dot" />
          <span class="stat-pill__value">{{ summary.up }}</span>
          <span class="stat-pill__label">attivi</span>
        </div>
        <div v-if="summary.degraded" class="stat-pill stat-pill--degraded">
          <span class="stat-pill__dot" />
          <span class="stat-pill__value">{{ summary.degraded }}</span>
          <span class="stat-pill__label">degradati</span>
        </div>
        <div v-if="summary.down" class="stat-pill stat-pill--down">
          <span class="stat-pill__dot" />
          <span class="stat-pill__value">{{ summary.down }}</span>
          <span class="stat-pill__label">spenti</span>
        </div>
        <div v-if="summary.starting" class="stat-pill stat-pill--starting">
          <span class="stat-pill__dot" />
          <span class="stat-pill__value">{{ summary.starting }}</span>
          <span class="stat-pill__label">avvio</span>
        </div>
        <div class="stat-pill stat-pill--neutral">
          <span class="stat-pill__value">{{ totalServices }}</span>
          <span class="stat-pill__label">totali</span>
        </div>
        <div v-if="activeDownloads > 0" class="stat-pill stat-pill--accent">
          <AppIcon name="download" :size="11" />
          <span class="stat-pill__value">{{ activeDownloads }}</span>
          <span class="stat-pill__label">{{ activeDownloads === 1 ? 'download' : 'download attivi' }}</span>
        </div>
      </div>

      <div v-if="store.error" class="services-view__error" role="alert">
        <AppIcon name="alert-triangle" :size="14" />
        <span>{{ store.error }}</span>
      </div>
    </header>

    <section v-if="stdServices.length" class="services-view__section">
      <div class="services-view__section-head">
        <h2 class="services-view__section-title">Microservizi</h2>
        <span class="services-view__section-count">{{ stdServices.length }}</span>
      </div>
      <div class="services-view__grid">
        <ServiceCard
          v-for="svc in stdServices"
          :key="svc.name"
          :service="svc"
          @restart="store.restart(svc.name)"
        />
      </div>
    </section>

    <section v-if="trellisServices.length" class="services-view__section">
      <div class="services-view__section-head">
        <h2 class="services-view__section-title">TRELLIS — Generazione 3D</h2>
        <span class="services-view__section-count">{{ trellisServices.length }}</span>
      </div>
      <div class="services-view__grid services-view__grid--wide">
        <TrellisConfigCard
          v-for="svc in trellisServices"
          :key="svc.name"
          :service="svc"
          @restart="store.restart(svc.name)"
          @open-guide="showGuide = true"
        />
      </div>
    </section>

    <div v-if="!store.services.length && !store.error" class="services-view__empty">
      <AppIcon name="server" :size="32" />
      <p>Nessun servizio registrato.</p>
    </div>

    <TrellisSetupGuideModal v-if="showGuide" @close="showGuide = false" />
  </main>
</template>

<style scoped>
/* ── Page shell ───────────────────────────────────────────────── */
.services-view {
  padding: var(--space-8);
  max-width: 1180px;
  margin: 0 auto;
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
  gap: var(--space-8);
}

/* ── Header ───────────────────────────────────────────────────── */
.services-view__head {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.services-view__head-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}
.services-view__title-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.services-view__title {
  margin: 0;
  font-size: var(--text-2xl);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}
.services-view__subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: var(--leading-snug);
  max-width: 64ch;
}
.services-view__refresh {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
}
.services-view__refresh:hover:not(:disabled) {
  background: var(--surface-3);
  color: var(--text-primary);
  border-color: var(--border-hover);
}
.services-view__refresh:disabled {
  opacity: 0.6;
  cursor: default;
}
.is-spinning {
  animation: services-spin 0.9s linear infinite;
}
@keyframes services-spin {
  to { transform: rotate(360deg); }
}

/* ── Stats pills ─────────────────────────────────────────────── */
.services-view__stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.stat-pill {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1-5) var(--space-3);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  letter-spacing: var(--tracking-tight);
}
.stat-pill__dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: currentColor;
  box-shadow: 0 0 8px currentColor;
}
.stat-pill__value {
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.stat-pill__label {
  text-transform: lowercase;
}
.stat-pill--up { color: var(--success); }
.stat-pill--up .stat-pill__value { color: var(--success); }
.stat-pill--degraded { color: var(--warning); }
.stat-pill--degraded .stat-pill__value { color: var(--warning); }
.stat-pill--down { color: var(--danger); }
.stat-pill--down .stat-pill__value { color: var(--danger); }
.stat-pill--starting { color: var(--accent); }
.stat-pill--starting .stat-pill__value { color: var(--accent); }
.stat-pill--accent {
  background: var(--accent-dim);
  border-color: var(--accent-border);
  color: var(--accent);
}
.stat-pill--accent .stat-pill__value { color: var(--accent); }
.stat-pill--neutral .stat-pill__value { color: var(--text-secondary); }

/* ── Error banner ────────────────────────────────────────────── */
.services-view__error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--danger-faint);
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-md);
  color: var(--danger);
  font-size: var(--text-sm);
}

/* ── Sections ────────────────────────────────────────────────── */
.services-view__section {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.services-view__section-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border);
}
.services-view__section-title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}
.services-view__section-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 20px;
  padding: 0 var(--space-2);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.services-view__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-4);
}
.services-view__grid--wide {
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
}

/* ── Empty state ─────────────────────────────────────────────── */
.services-view__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
  background: var(--surface-1);
  border: 1px dashed var(--border);
  border-radius: var(--radius-lg);
  color: var(--text-muted);
  gap: var(--space-3);
  font-size: var(--text-sm);
}
.services-view__empty p { margin: 0; }
</style>
