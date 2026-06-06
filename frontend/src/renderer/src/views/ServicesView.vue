<script setup lang="ts">
/**
 * ServicesView — Service status & configuration, master-detail layout.
 *
 * Left rail = single selectable list of ALL managed services (standard +
 * TRELLIS, grouped with sub-labels). Right pane = the full detail of the
 * selected service, rendered by reusing the existing per-service
 * components:
 *
 * - `ServiceCard`        for standard services (LM Studio, STT, TTS, VRAM…)
 * - `TrellisConfigCard`  for the TRELLIS 3D-generation family.
 *
 * All behaviour (refresh, start/stop/restart, model downloads, TRELLIS
 * config form + setup-guide modal) lives inside those components and the
 * services store — this view only adds local selection state.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useServicesStore, type ServiceSnapshot } from '../stores/services'
import type { AppIconName } from '../assets/icons'
import AppIcon from '../components/ui/AppIcon.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import ServiceCard from '../components/services/ServiceCard.vue'
import TrellisConfigCard from '../components/services/TrellisConfigCard.vue'
import TrellisSetupGuideModal from '../components/services/TrellisSetupGuideModal.vue'

const store = useServicesStore()
const showGuide = ref(false)
const guideService = ref<TrellisGuideService>('trellis2')

function openGuide(svc: TrellisGuideService): void {
  guideService.value = svc
  showGuide.value = true
}

function openGuideForService(name: string): void {
  // Narrowing helper for the template: only the two known multi-step
  // services have a markdown guide; classic ``trellis`` (text-to-3D)
  // doesn't surface this button.
  if (name === 'trellis2' || name === 'trellis2multiview') {
    openGuide(name)
  }
}
const refreshing = ref(false)

onMounted(() => {
  void store.refresh()
  void store.loadCatalog('stt')
  void store.loadCatalog('tts')
})

// Names of the Trellis-family services that get the dedicated
// configuration card (instead of the generic ServiceCard).  Kept as a
// const so adding a new variant only requires updating this list.
const TRELLIS_NAMES = ['trellis', 'trellis2', 'trellis2multiview'] as const
type TrellisGuideService = 'trellis2' | 'trellis2multiview'

function isTrellis(name: string): boolean {
  return TRELLIS_NAMES.includes(name as (typeof TRELLIS_NAMES)[number])
}

const stdServices = computed(() =>
  store.services.filter((s) => !isTrellis(s.name)),
)
const trellisServices = computed(() =>
  store.services.filter((s) => isTrellis(s.name)),
)

// ── Row display metadata (icon + human label) ───────────────────
const STATUS_LABELS: Record<string, string> = {
  up: 'Attivo',
  down: 'Spento',
  degraded: 'Degradato',
  starting: 'Avvio…',
}
const SERVICE_LABELS: Record<string, { label: string; icon: AppIconName }> = {
  llm: { label: 'LM Studio', icon: 'server' },
  stt: { label: 'Speech-to-Text', icon: 'mic' },
  tts: { label: 'Text-to-Speech', icon: 'volume' },
  vram: { label: 'VRAM Monitor', icon: 'cpu' },
  trellis: { label: 'TRELLIS', icon: 'box-3d' },
  trellis2: { label: 'TRELLIS.2', icon: 'box-3d' },
  trellis2multiview: { label: 'TRELLIS.2 Multi-view', icon: 'box-3d' },
}
function metaFor(svc: ServiceSnapshot): { label: string; icon: AppIconName } {
  return SERVICE_LABELS[svc.name] ?? { label: svc.name, icon: 'server' }
}
function statusLabelFor(svc: ServiceSnapshot): string {
  return STATUS_LABELS[svc.status] ?? svc.status
}

// ── Header summary ──────────────────────────────────────────────
const upCount = computed(
  () => store.services.filter((s) => s.status === 'up').length,
)
const totalServices = computed(() => store.services.length)
const activeDownloads = computed(
  () => Object.values(store.downloads).filter((d) => d.phase === 'downloading').length,
)
const overallClass = computed(() => {
  if (!totalServices.value) return 'is-neutral'
  if (store.services.some((s) => s.status === 'down')) return 'is-down'
  if (store.services.some((s) => s.status === 'degraded')) return 'is-degraded'
  if (store.services.some((s) => s.status === 'starting')) return 'is-starting'
  return 'is-up'
})

// ── Selection (local view state only) ───────────────────────────
const selectedServiceName = ref<string | null>(null)

watch(
  () => store.services,
  (list) => {
    if (!list.length) {
      selectedServiceName.value = null
      return
    }
    // Default to first service, and stay valid if the list changes / the
    // selected service disappears.
    if (
      !selectedServiceName.value ||
      !list.some((s) => s.name === selectedServiceName.value)
    ) {
      selectedServiceName.value = list[0].name
    }
  },
  { immediate: true },
)

const selectedService = computed<ServiceSnapshot | null>(
  () => store.services.find((s) => s.name === selectedServiceName.value) ?? null,
)
const selectedIsTrellis = computed(() =>
  selectedService.value ? isTrellis(selectedService.value.name) : false,
)

function select(name: string): void {
  selectedServiceName.value = name
}

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
      <div class="services-view__title-block">
        <h1 class="services-view__title">Servizi</h1>
        <p class="services-view__subtitle">
          Stato dei microservizi locali, gestione dei modelli STT/TTS e configurazione 3D.
        </p>
      </div>

      <div class="services-view__head-aside">
        <span
          class="services-view__overall"
          :class="overallClass"
          :title="`${upCount} di ${totalServices} servizi attivi`"
        >
          <span class="services-view__overall-dot" />
          <span class="services-view__overall-value">{{ upCount }}/{{ totalServices }}</span>
          <span class="services-view__overall-label">attivi</span>
        </span>
        <span v-if="activeDownloads > 0" class="services-view__overall is-accent">
          <AppIcon name="download" :size="11" />
          <span class="services-view__overall-value">{{ activeDownloads }}</span>
          <span class="services-view__overall-label">download</span>
        </span>
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
    </header>

    <div v-if="store.error" class="services-view__error" role="alert">
      <AppIcon name="alert-triangle" :size="14" />
      <span>{{ store.error }}</span>
    </div>

    <div class="services-view__body">
      <nav
        v-if="store.services.length"
        class="services-view__rail"
        aria-label="Elenco servizi"
      >
        <template v-if="stdServices.length">
          <p class="services-view__rail-label">Microservizi</p>
          <button
            v-for="svc in stdServices"
            :key="svc.name"
            type="button"
            class="rail-row"
            :class="[`is-${svc.status}`, { 'is-selected': svc.name === selectedServiceName }]"
            :aria-current="svc.name === selectedServiceName ? 'true' : undefined"
            @click="select(svc.name)"
          >
            <span class="rail-row__dot" :class="`is-${svc.status}`" />
            <span class="rail-row__icon"><AppIcon :name="metaFor(svc).icon" :size="15" /></span>
            <span class="rail-row__name">{{ metaFor(svc).label }}</span>
            <span class="rail-row__status">{{ statusLabelFor(svc) }}</span>
          </button>
        </template>

        <template v-if="trellisServices.length">
          <p class="services-view__rail-label">TRELLIS — 3D</p>
          <button
            v-for="svc in trellisServices"
            :key="svc.name"
            type="button"
            class="rail-row"
            :class="[`is-${svc.status}`, { 'is-selected': svc.name === selectedServiceName }]"
            :aria-current="svc.name === selectedServiceName ? 'true' : undefined"
            @click="select(svc.name)"
          >
            <span class="rail-row__dot" :class="`is-${svc.status}`" />
            <span class="rail-row__icon"><AppIcon :name="metaFor(svc).icon" :size="15" /></span>
            <span class="rail-row__name">{{ metaFor(svc).label }}</span>
            <span class="rail-row__status">{{ statusLabelFor(svc) }}</span>
          </button>
        </template>
      </nav>

      <section class="services-view__detail">
        <div v-if="selectedService" class="services-view__detail-inner">
          <TrellisConfigCard
            v-if="selectedIsTrellis"
            :key="selectedService.name"
            :service="selectedService"
            @open-guide="openGuideForService(selectedService.name)"
          />
          <ServiceCard
            v-else
            :key="selectedService.name"
            :service="selectedService"
            @restart="store.restart(selectedService.name)"
          />
        </div>
        <UiEmptyState
          v-else-if="!store.error"
          icon="server"
          title="Nessun servizio registrato"
        />
      </section>
    </div>

    <TrellisSetupGuideModal
      v-if="showGuide"
      :service="guideService"
      @close="showGuide = false"
    />
  </main>
</template>

<style scoped>
/* ── Page shell ───────────────────────────────────────────────── */
.services-view {
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  padding: var(--space-6) clamp(var(--space-4), 3vw, var(--space-8)) var(--space-6);
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  background: var(--surface-0);
}

/* ── Header (blended onto surface, no bordered panel) ─────────── */
.services-view__head {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}
.services-view__title-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}
.services-view__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  letter-spacing: 0;
  line-height: var(--leading-tight);
}
.services-view__subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: var(--leading-snug);
  max-width: 64ch;
}
.services-view__head-aside {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* ── Overall status pill ──────────────────────────────────────── */
.services-view__overall {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 30px;
  padding: 0 var(--space-3);
  background: var(--surface-1);
  border-radius: 8px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.services-view__overall-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: currentColor;
  box-shadow: 0 0 8px currentColor;
}
.services-view__overall-value {
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.services-view__overall-label {
  text-transform: lowercase;
}
.services-view__overall.is-up { color: var(--success); }
.services-view__overall.is-up .services-view__overall-value { color: var(--success); }
.services-view__overall.is-degraded { color: var(--warning); }
.services-view__overall.is-degraded .services-view__overall-value { color: var(--warning); }
.services-view__overall.is-down { color: var(--danger); }
.services-view__overall.is-down .services-view__overall-value { color: var(--danger); }
.services-view__overall.is-starting { color: var(--accent); }
.services-view__overall.is-starting .services-view__overall-value { color: var(--accent); }
.services-view__overall.is-neutral .services-view__overall-value { color: var(--text-secondary); }
.services-view__overall.is-accent {
  background: var(--accent-dim);
  color: var(--accent);
}
.services-view__overall.is-accent .services-view__overall-value { color: var(--accent); }

/* ── Refresh button ───────────────────────────────────────────── */
.services-view__refresh {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 30px;
  padding: 0 var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 8px;
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

/* ── Error banner ────────────────────────────────────────────── */
.services-view__error {
  flex: 0 0 auto;
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

/* ── Master-detail body ──────────────────────────────────────── */
.services-view__body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  gap: var(--space-4);
}

/* ── Left rail (master list) ─────────────────────────────────── */
.services-view__rail {
  flex: 0 0 272px;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2);
  background: var(--surface-1);
  border-radius: var(--radius-md);
}
.services-view__rail-label {
  margin: var(--space-2) var(--space-2) var(--space-1);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  text-transform: uppercase;
  letter-spacing: var(--tracking-wide);
  color: var(--text-muted);
}
.services-view__rail-label:first-child {
  margin-top: var(--space-1);
}

/* ── Rail row ─────────────────────────────────────────────────── */
.rail-row {
  display: flex;
  align-items: center;
  gap: var(--space-2-5);
  width: 100%;
  padding: var(--space-2) var(--space-2-5);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  color: var(--text-secondary);
  transition: background 120ms ease, color 120ms ease;
}
.rail-row:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}
.rail-row.is-selected {
  background: var(--surface-selected);
  color: var(--text-primary);
}
.rail-row:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--accent-border);
}
.rail-row__dot {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--text-muted);
  box-shadow: 0 0 6px transparent;
}
.rail-row__dot.is-up { background: var(--success); box-shadow: 0 0 6px var(--success); }
.rail-row__dot.is-degraded { background: var(--warning); box-shadow: 0 0 6px var(--warning); }
.rail-row__dot.is-down { background: var(--danger); }
.rail-row__dot.is-starting {
  background: var(--accent);
  animation: status-pulse 1.4s ease-in-out infinite;
}
@keyframes status-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.85); }
}
.rail-row__icon {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}
.rail-row.is-selected .rail-row__icon {
  color: var(--text-secondary);
}
.rail-row__name {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rail-row__status {
  flex: 0 0 auto;
  font-size: var(--text-2xs);
  color: var(--text-muted);
  letter-spacing: var(--tracking-tight);
}

/* ── Right detail pane ───────────────────────────────────────── */
.services-view__detail {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
}
.services-view__detail-inner {
  max-width: 680px;
}

@media (max-width: 760px) {
  .services-view {
    padding: var(--space-4) var(--space-3) var(--space-4);
    overflow-y: auto;
  }
  .services-view__head {
    flex-direction: column;
    align-items: stretch;
  }
  .services-view__head-aside {
    flex-wrap: wrap;
  }
  .services-view__refresh {
    margin-left: auto;
  }
  .services-view__body {
    flex-direction: column;
    overflow: visible;
  }
  .services-view__rail {
    flex: 0 0 auto;
    max-height: 280px;
  }
  .services-view__detail {
    overflow-y: visible;
  }
  .services-view__detail-inner {
    max-width: none;
  }
}
</style>
